import asyncio
from contextlib import suppress
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent, TelegramObject, BotCommand, MenuButtonCommands
from aiogram import BaseMiddleware
from aiogram.fsm.storage.memory import MemoryStorage
from typing import Callable, Dict, Any, Awaitable

from bot.config import settings
from bot.database.engine import async_session_maker, init_db
from bot.database.repositories import CategoryRepository
from bot.handlers.language import LanguageMiddleware, router as language_router
from bot.handlers import autopay, commands, voice, text, callbacks, expense_history
from bot.services.pay_webhook import start_pay_webhook_server

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Middleware for injecting SQLAlchemy async sessions into handlers."""
    def __init__(self, session_pool):
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        async with self.session_pool() as session:
            data['session'] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


async def set_bot_commands(bot: Bot):
    """Publish the default slash-command suggestions."""
    await bot.set_my_commands([
        BotCommand(command="start", description="Boshlash / Начать"),
    ])


async def on_startup(bot: Bot):
    """Run startup tasks: init DB, seed categories, set bot commands, restore the command menu."""
    logger.info("Initializing database...")
    await init_db()

    async with async_session_maker() as session:
        await CategoryRepository.seed_defaults(session)
        await session.commit()

    await set_bot_commands(bot)

    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    logger.info("Startup complete.")


async def main():
    """Main application entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Register Middlewares
    dp.update.middleware(DbSessionMiddleware(async_session_maker))

    language = LanguageMiddleware()
    dp.message.outer_middleware(language)
    dp.callback_query.outer_middleware(language)

    # Register menu actions before generic voice and text handling.
    dp.include_router(language_router)
    dp.include_router(autopay.router)
    dp.include_router(commands.router)
    dp.include_router(expense_history.router)
    dp.include_router(voice.router)
    dp.include_router(text.router)
    dp.include_router(callbacks.router)

    dp.startup.register(on_startup)
    finance_task = None
    webhook_runner = None

    async def start_background_services(bot: Bot):
        nonlocal finance_task, webhook_runner
        from bot.services.finance_worker import finance_worker
        finance_task = asyncio.create_task(finance_worker(async_session_maker, bot))
        webhook_runner = await start_pay_webhook_server(bot=bot, session_pool=async_session_maker)

    dp.startup.register(start_background_services)

    @dp.errors()
    async def on_dispatcher_error(event: ErrorEvent) -> bool:
        logger.error(
            "Unhandled bot update error (%s)",
            type(event.exception).__name__,
            exc_info=event.exception,
        )
        return True

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        if webhook_runner:
            await webhook_runner.cleanup()
        if finance_task:
            finance_task.cancel()
            with suppress(asyncio.CancelledError): await finance_task
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
