import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import TelegramObject, BotCommand
from aiogram import BaseMiddleware
from aiogram.fsm.storage.memory import MemoryStorage
from typing import Callable, Dict, Any, Awaitable

from bot.config import settings
from bot.database.engine import async_session_maker, init_db
from bot.database.repositories import CategoryRepository
from bot.handlers import commands, voice, text, callbacks, balance, csv_import, web_login

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
    """Set bot commands menu."""
    commands = [
        BotCommand(command="start", description="Запустить/перезапустить бота"),
        BotCommand(command="app", description="Открыть приложение Mone"),
        BotCommand(command="today", description="Расходы за сегодня"),
        BotCommand(command="week", description="Расходы за неделю"),
        BotCommand(command="month", description="Расходы за месяц"),
        BotCommand(command="import", description="Импорт расходов и доходов из CSV"),
        BotCommand(command="reset", description="Удалить все данные (сброс)"),
    ]
    await bot.set_my_commands(commands)


async def on_startup(bot: Bot):
    """Run startup tasks: init DB, seed categories, set bot commands, set webapp menu button."""
    logger.info("Initializing database...")
    await init_db()

    async with async_session_maker() as session:
        await CategoryRepository.seed_defaults(session)
        await session.commit()

    await set_bot_commands(bot)

    if settings.WEB_PUBLIC_URL:
        try:
            from aiogram.types import MenuButtonWebApp, WebAppInfo
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="📱 Кабинет",
                    web_app=WebAppInfo(url=settings.WEB_PUBLIC_URL),
                )
            )
            logger.info("Chat menu button set to WebApp: %s", settings.WEB_PUBLIC_URL)
        except Exception as e:
            logger.warning("Could not set chat menu button: %s", e)

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

    # Include routers — balance must come before text to avoid FSM state conflicts
    dp.include_router(web_login.router)
    dp.include_router(csv_import.router)
    dp.include_router(commands.router)
    dp.include_router(balance.router)
    dp.include_router(voice.router)
    dp.include_router(text.router)
    dp.include_router(callbacks.router)

    dp.startup.register(on_startup)

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
