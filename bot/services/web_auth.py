"""One-time Telegram approvals. Raw browser/session secrets are never stored."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.web_session import WebLoginRequest, WebSession


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def is_expired(value: datetime) -> bool:
    return value.replace(tzinfo=value.tzinfo or timezone.utc) <= datetime.now(timezone.utc)


async def request_login(session: AsyncSession) -> tuple[WebLoginRequest, str]:
    secret = secrets.token_urlsafe(32)
    item = WebLoginRequest(id=secrets.token_hex(16), browser_hash=digest(secret),
                           expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    session.add(item)
    await session.flush()
    return item, f"{item.id}.{secret}"


async def approve_login(session: AsyncSession, request_id: str, user_id: int) -> bool:
    item = (await session.execute(select(WebLoginRequest).where(
        WebLoginRequest.id == request_id).with_for_update())).scalar_one_or_none()
    if item is None or item.consumed or item.user_id is not None or is_expired(item.expires_at):
        return False
    item.user_id = user_id
    await session.flush()
    return True


async def consume_login(session: AsyncSession, browser_cookie: str) -> tuple[str, str | None]:
    request_id, separator, secret = browser_cookie.partition(".")
    if not separator:
        return "expired", None
    item = (await session.execute(select(WebLoginRequest).where(
        WebLoginRequest.id == request_id).with_for_update())).scalar_one_or_none()
    if item is None or not secrets.compare_digest(item.browser_hash, digest(secret)):
        return "expired", None
    if item.consumed or is_expired(item.expires_at):
        return "expired", None
    if item.user_id is None:
        return "pending", None
    token = secrets.token_urlsafe(32)
    session.add(WebSession(token_hash=digest(token), user_id=item.user_id,
                           expires_at=datetime.now(timezone.utc) + timedelta(days=7)))
    item.consumed = True
    await session.flush()
    return "approved", token
