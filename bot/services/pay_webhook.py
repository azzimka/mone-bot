"""Lightweight aiohttp webhook server for Google Wallet / Android payment notifications."""

from collections import deque
import json
import logging
import time
import uuid

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
from sqlalchemy import select

from bot.config import settings
from bot.database.repositories import UserRepository
from bot.handlers.callbacks import pending_transactions
from bot.models import Category
from bot.services.ai_parser import AIParser
from bot.services.i18n import current_category_names, current_language, tr
from bot.services.reports import ReportService

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 16 * 1024
DEDUP_WINDOW_SECONDS = 60.0
PARSED_DEDUP_WINDOW_SECONDS = 30.0
RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_MAX_REQUESTS = 20


def _extract_token(request: web.Request, payload: dict) -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header_token = (request.headers.get("X-Webhook-Token") or "").strip()
    if header_token:
        return header_token
    body_token = payload.get("token")
    return body_token.strip() if isinstance(body_token, str) else ""


def _extract_notification_fields(payload: dict, raw_text: str) -> tuple[str, str]:
    title = ""
    for key in ("title", "notif_title", "app"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            title = value.strip()
            break
    text = ""
    for key in ("text", "notif_text", "body", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            break
    if not title and not text and raw_text.strip():
        text = raw_text.strip()
    return title[:500], text[:1500]


def _extract_source_name(payload: dict) -> str:
    app = payload.get("app")
    if isinstance(app, str) and app.strip():
        cleaned = app.strip()[:40]
        for ch in ("*", "_", "`", "["):
            cleaned = cleaned.replace(ch, "")
        if cleaned:
            return cleaned
    return "Google Wallet"


def create_pay_webhook_app(
    bot: Bot,
    session_pool,
    ai_parser: AIParser | None = None,
    report_service: ReportService | None = None,
) -> web.Application:
    parser = ai_parser or AIParser(api_key=settings.GROQ_API_KEY)
    reports = report_service or ReportService()
    recent_events: dict[tuple[int, str], float] = {}
    recent_parsed: dict[tuple[int, str, str], float] = {}
    rate_buckets: dict[int, deque[float]] = {}

    def _is_rate_limited(user_id: int, now: float) -> bool:
        bucket = rate_buckets.setdefault(user_id, deque())
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            return True
        bucket.append(now)
        return False

    def _is_duplicate(user_id: int, fingerprint: str, now: float) -> bool:
        expired = [key for key, ts in recent_events.items() if now - ts > DEDUP_WINDOW_SECONDS]
        for key in expired:
            recent_events.pop(key, None)
        cache_key = (user_id, fingerprint)
        if cache_key in recent_events:
            return True
        recent_events[cache_key] = now
        return False

    def _is_parsed_duplicate(user_id: int, amount_key: str, currency: str, now: float) -> bool:
        expired = [key for key, ts in recent_parsed.items() if now - ts > PARSED_DEDUP_WINDOW_SECONDS]
        for key in expired:
            recent_parsed.pop(key, None)
        cache_key = (user_id, amount_key, currency)
        if cache_key in recent_parsed:
            return True
        recent_parsed[cache_key] = now
        return False

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def handle_google_pay(request: web.Request) -> web.Response:
        raw_bytes = await request.content.read(MAX_BODY_BYTES + 1)
        if len(raw_bytes) > MAX_BODY_BYTES:
            return web.json_response({"error": "payload_too_large"}, status=413)
        raw_text = raw_bytes.decode("utf-8", errors="replace")

        payload: dict = {}
        if raw_text.strip():
            try:
                loaded = json.loads(raw_text)
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = {}

        token = _extract_token(request, payload)
        if not token:
            return web.json_response({"error": "unauthorized"}, status=401)

        async with session_pool() as session:
            user = await UserRepository.get_by_pay_token(session, token)
            if user is None:
                return web.json_response({"error": "unauthorized"}, status=401)
            custom_rows = (
                await session.execute(select(Category).where(Category.user_id == user.id))
            ).scalars().all()

        now = time.monotonic()
        if _is_rate_limited(user.id, now):
            return web.json_response({"error": "rate_limited"}, status=429)

        title, text = _extract_notification_fields(payload, raw_text)
        if not title and not text:
            return web.json_response({"status": "ignored", "reason": "empty"})

        fingerprint = " ".join(f"{title}\n{text}".casefold().split())
        if _is_duplicate(user.id, fingerprint, now):
            return web.json_response({"status": "duplicate"})

        parsed = await parser.parse_payment_notification(title, text, user.default_currency)
        if not parsed or not parsed.transactions:
            return web.json_response({"status": "ignored"})

        # Deduplicate across apps (e.g., Google Wallet + Uzum Bank firing for the same payment)
        parsed_now = time.monotonic()
        unique_txs = [
            tx
            for tx in parsed.transactions
            if not _is_parsed_duplicate(user.id, format(tx.amount.normalize(), "f"), tx.currency, parsed_now)
        ]
        if not unique_txs:
            return web.json_response({"status": "duplicate"})

        source_name = _extract_source_name(payload)
        lang_token = current_language.set(user.language or "ru")
        cat_token = current_category_names.set(
            {
                item.name: (item.name_ru if user.language == "ru" else item.name_uz) or item.display_name
                for item in custom_rows
                if (item.name_ru if user.language == "ru" else item.name_uz) or item.display_name
            }
        )
        sent = 0
        try:
            source_text = f"{title}: {text}".strip(": ")
            total_txs = len(unique_txs)
            for idx, tx in enumerate(unique_txs, start=1):
                tx_id = str(uuid.uuid4())
                pending_transactions[tx_id] = {
                    "user_id": user.id,
                    "transaction": tx.model_dump(),
                    "voice_text": source_text,
                }
                builder = InlineKeyboardBuilder()
                builder.button(text=tr("✅ Верно"), callback_data=f"confirm:{tx_id}")
                builder.button(text=tr("❌ Отменить"), callback_data=f"cancel:{tx_id}")
                builder.adjust(2)

                header = f"💳 *{source_name}*\n"
                if total_txs > 1:
                    header += tr("*{p1} из {p3}*\n", p1=f"{idx}", p3=f"{total_txs}")
                card_text = header + reports.format_transaction_confirmation(tx)
                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=card_text,
                    reply_markup=builder.as_markup(),
                    parse_mode="Markdown",
                )
                sent += 1
        except Exception as exc:
            logger.error("Failed to deliver Google Wallet confirmation (%s)", type(exc).__name__)
            return web.json_response({"error": "delivery_failed"}, status=502)
        finally:
            current_category_names.reset(cat_token)
            current_language.reset(lang_token)

        return web.json_response({"status": "sent", "count": sent})

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/webhook/google-pay", handle_google_pay)
    app.router.add_post("/webhook/pay", handle_google_pay)
    return app


async def start_pay_webhook_server(
    bot: Bot,
    session_pool,
    host: str | None = None,
    port: int | None = None,
) -> web.AppRunner:
    app = create_pay_webhook_app(bot=bot, session_pool=session_pool)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    bind_host = host or settings.WEBHOOK_HOST
    bind_port = port if port is not None else settings.WEBHOOK_PORT
    site = web.TCPSite(runner, host=bind_host, port=bind_port)
    await site.start()
    logger.info("Payment webhook server listening on %s:%s", bind_host, bind_port)
    return runner
