"""Same-origin web API and static Next.js export, backed by the bot's ledger."""

import json
import logging
import re
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram.utils.web_app import safe_parse_webapp_init_data
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import WebSettings
from api.schemas import CategoryInput, CategoryUpdate, PreferencesInput, TelegramWebAppData, TransactionInput
from bot.database.repositories import UserRepository
from bot.database.schema import initialize_schema
from bot.models import Category, Transaction, User, WebLoginRequest, WebSession
from bot.services.categories import category_catalog, validate_category
from bot.services.web_auth import consume_login, digest, is_expired, request_login

logger = logging.getLogger(__name__)
SESSION_COOKIE = "mone_session"
LOGIN_COOKIE = "mone_login"


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.pool() as session:
        yield session


async def get_user(request: Request, session: AsyncSession = Depends(get_session)) -> User:
    token = request.cookies.get(SESSION_COOKIE, "")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ").strip()
    if not token:
        init_data_raw = request.headers.get("X-Telegram-Init-Data", "")
        bot_token = getattr(request.app.state, "bot_token", "")
        if init_data_raw and bot_token:
            try:
                parsed = safe_parse_webapp_init_data(token=bot_token, init_data=init_data_raw)
                age = (datetime.now(timezone.utc) - parsed.auth_date).total_seconds()
                if parsed.user and parsed.user.id and age <= 86400 * 3:
                    return await UserRepository.get_or_create(
                        session=session,
                        telegram_id=parsed.user.id,
                        username=parsed.user.username,
                        first_name=parsed.user.first_name,
                    )
            except Exception:
                pass
        raise HTTPException(401, "Telegram orqali kiring.")
    user = (await session.execute(select(User).join(WebSession).where(
        WebSession.token_hash == digest(token), WebSession.expires_at > datetime.now(timezone.utc)
    ))).scalar_one_or_none()
    if user is None:
        raise HTTPException(401, "Sessiya tugagan. Qayta kiring.")
    return user


def serialize_tx(tx: Transaction) -> dict:
    return {"id": tx.id, "account_id":tx.account_id,"type": tx.type, "amount": str(tx.amount), "currency": tx.currency,
            "category": tx.category or "Другое", "description": tx.description or "",
            "date": tx.date.isoformat()}


def user_json(user: User, bot_username: str = "") -> dict:
    return {"first_name": user.first_name or "Mone foydalanuvchisi", "username": user.username,
            "currency": user.default_currency, "language": user.language,
            "timezone": user.timezone or "Asia/Tashkent", "week_start": user.week_start or 0,
            "quick_categories": json.loads(user.quick_categories or "[]"),
            "language_url": f"https://t.me/{bot_username.lstrip('@')}?start=language" if bot_username else None,
            "bot_url": f"https://t.me/{bot_username.lstrip('@')}" if bot_username else None}


def period(start: date | None, end: date | None) -> tuple[date, date]:
    today = datetime.now(ZoneInfo("Asia/Tashkent")).date()
    end = end or today
    start = start or today.replace(day=1)
    if start > end or (end - start).days > 3660:
        raise HTTPException(422, "Davr noto‘g‘ri yoki 10 yildan uzun.")
    return start, end


def ledger_filter(user: User, currency: str | None = None):
    return (Transaction.user_id == user.id, Transaction.currency == (currency or user.default_currency))

async def report_scope(session, user, currency, account_id):
    from bot.models import Account
    if account_id is not None:
        item=(await session.execute(select(Account).where(Account.user_id==user.id,Account.id==account_id))).scalar_one_or_none()
        if item is None:raise HTTPException(404,"Hisob topilmadi.")
        currency=item.currency
    currency=currency or user.default_currency
    return [*ledger_filter(user,currency),*([Transaction.account_id==account_id] if account_id else [])],currency



def create_app(config: WebSettings | None = None, pool: async_sessionmaker | None = None) -> FastAPI:
    config = config or WebSettings()
    secure = config.WEB_PUBLIC_URL.startswith("https://")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = None
        if pool is None:
            engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
            await initialize_schema(engine)
            app.state.pool = async_sessionmaker(engine, expire_on_commit=False)
        else:
            app.state.pool = pool
        yield
        if engine:
            await engine.dispose()

    app = FastAPI(title="Mone API", version="0.1.0", lifespan=lifespan)
    app.state.bot_token = config.TELEGRAM_BOT_TOKEN
    if pool is not None:
        app.state.pool = pool
    app.add_middleware(CORSMiddleware, allow_origins=[config.WEB_PUBLIC_URL],
                       allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "Authorization", "X-Telegram-Init-Data"])

    cookie_samesite = "none" if secure else "lax"

    @app.middleware("http")
    async def browser_security(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method in {"POST", "PATCH", "DELETE", "PUT"}:
            if request.headers.get("origin") != config.WEB_PUBLIC_URL:
                return JSONResponse({"detail": "So‘rov manbasi ruxsat etilmagan."}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org https://*.t.me;"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        logger.error("Web database request failed (%s)", type(exc).__name__)
        return JSONResponse({"detail": "Baza bilan aloqa uzildi. Qayta urinib ko‘ring."}, status_code=503)

    @app.get("/api/health")
    async def health(session: AsyncSession = Depends(get_session)):
        await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/api/auth/telegram/webapp")
    async def webapp_login(request: Request, body: TelegramWebAppData, response: Response, session: AsyncSession = Depends(get_session)):
        bot_token = getattr(request.app.state, "bot_token", "") or config.TELEGRAM_BOT_TOKEN
        if not bot_token:
            raise HTTPException(503, "Serverda TELEGRAM_BOT_TOKEN sozlanmagan.")
        try:
            init_data = safe_parse_webapp_init_data(token=bot_token, init_data=body.init_data)
        except Exception as e:
            logger.warning("Failed to validate webapp init_data: %s", e)
            raise HTTPException(401, "Noto‘g‘ri Telegram ma‘lumotlari.")

        if not init_data.user or not init_data.user.id:
            raise HTTPException(400, "Foydalanuvchi ma'lumoti topilmadi.")

        if init_data.auth_date:
            age = (datetime.now(timezone.utc) - init_data.auth_date).total_seconds()
            if age > 86400 * 3:
                raise HTTPException(401, "Telegram ma'lumotlarining muddati o'tgan.")

        user = await UserRepository.get_or_create(
            session=session,
            telegram_id=init_data.user.id,
            username=init_data.user.username,
            first_name=init_data.user.first_name,
        )

        token = secrets.token_urlsafe(32)
        session.add(WebSession(
            token_hash=digest(token),
            user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        ))
        await session.commit()

        response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite=cookie_samesite,
                            max_age=30 * 24 * 3600, path="/api")
        return {"status": "ok", "token": token, "user": user_json(user, config.TELEGRAM_BOT_USERNAME)}

    @app.post("/api/auth/telegram/request")
    async def login_request(response: Response, request: Request, session: AsyncSession = Depends(get_session)):
        username = config.TELEGRAM_BOT_USERNAME.lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            raise HTTPException(503, "Serverda TELEGRAM_BOT_USERNAME sozlanmagan.")
        # Reuse an unexpired request from this browser rather than storing one per click.
        cookie = request.cookies.get(LOGIN_COOKIE, "")
        request_id, _, secret = cookie.partition(".")
        item = await session.get(WebLoginRequest, request_id) if len(request_id) == 32 else None
        if item is None or item.consumed or is_expired(item.expires_at) or item.browser_hash != digest(secret):
            now = datetime.now(timezone.utc)
            await session.execute(delete(WebLoginRequest).where(WebLoginRequest.expires_at <= now))
            await session.execute(delete(WebSession).where(WebSession.expires_at <= now))
            item, cookie = await request_login(session)
        await session.commit()
        response.set_cookie(LOGIN_COOKIE, cookie, httponly=True, secure=secure, samesite=cookie_samesite,
                            max_age=300, path="/api/auth")
        return {"url": f"https://t.me/{username}?start=web_{item.id}", "code": item.id[:6].upper()}

    @app.post("/api/auth/telegram/poll")
    async def login_poll(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
        status, token = await consume_login(session, request.cookies.get(LOGIN_COOKIE, ""))
        await session.commit()
        if token:
            response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite=cookie_samesite,
                                max_age=30 * 24 * 3600, path="/api")
            response.delete_cookie(LOGIN_COOKIE, path="/api/auth")
        return {"status": status, "token": token}

    @app.get("/api/me")
    async def me(user: User = Depends(get_user)):
        return user_json(user, config.TELEGRAM_BOT_USERNAME)

    @app.patch("/api/preferences")
    async def preferences(body: PreferencesInput, user: User = Depends(get_user),
                          session: AsyncSession = Depends(get_session)):
        if user.language is None:
            raise HTTPException(409, "Avval botda tilni tanlang")
        from bot.services.categories import category_catalog
        values=body.model_dump(exclude_none=True)
        if "quick_categories" in values:
            available={item["name"] for item in await category_catalog(session,user.id) if not item["archived"]}
            if len(set(values["quick_categories"]))!=len(values["quick_categories"]) or not set(values["quick_categories"]).issubset(available):raise HTTPException(422,"Tezkor kategoriyalarni tekshiring.")
        for key,value in values.items():
            setattr(user,"default_currency" if key=="currency" else key,json.dumps(value) if key=="quick_categories" else value)
        await session.commit()
        return user_json(user, config.TELEGRAM_BOT_USERNAME)

    @app.post("/api/auth/logout", status_code=204)
    async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
        token = request.cookies.get(SESSION_COOKIE, "")
        if not token and request.headers.get("Authorization", "").startswith("Bearer "):
            token = request.headers["Authorization"].removeprefix("Bearer ").strip()
        await session.execute(delete(WebSession).where(WebSession.token_hash == digest(token)))
        await session.commit()
        response.delete_cookie(SESSION_COOKIE, path="/api")
        response.delete_cookie(LOGIN_COOKIE, path="/api/auth")

    @app.get("/api/categories")
    async def categories(user: User = Depends(get_user), session: AsyncSession = Depends(get_session)):
        return [item["name"] for item in await category_catalog(session, user.id)]

    @app.get("/api/category-settings")
    async def category_settings(user: User = Depends(get_user), session: AsyncSession = Depends(get_session)):
        return await category_catalog(session, user.id)

    @app.post("/api/categories", status_code=201)
    async def create_category(body: CategoryInput, user: User = Depends(get_user),
                              session: AsyncSession = Depends(get_session)):
        from sqlalchemy.exc import IntegrityError
        catalog = await category_catalog(session, user.id)
        try:
            validate_category(catalog, body.name, body.parent_name)
            for label in [body.name_uz,body.name_ru]:
                if label:validate_category(catalog,label,body.parent_name)
        except ValueError as error:
            raise HTTPException(409, str(error))
        session.add(Category(name=body.name, name_uz=body.name_uz,name_ru=body.name_ru,icon=body.icon, parent_name=body.parent_name,
                             user_id=user.id, is_default=False))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(409, "Bunday kategoriya mavjud.")
        return {"name": body.name}

    @app.patch("/api/category-settings")
    async def edit_category(body: CategoryUpdate, user: User = Depends(get_user),
                            session: AsyncSession = Depends(get_session)):
        from sqlalchemy.exc import IntegrityError
        catalog = await category_catalog(session, user.id)
        if not any(item["name"] == body.key for item in catalog):
            raise HTTPException(404, "Kategoriya topilmadi.")
        try:
            validate_category(catalog, body.name, body.parent_name, body.key)
            for label in [body.name_uz,body.name_ru]:
                if label:validate_category(catalog,label,body.parent_name,body.key)
        except ValueError as error:
            raise HTTPException(409, str(error))
        record = (await session.execute(select(Category).where(
            Category.user_id == user.id, Category.name == body.key))).scalar_one_or_none()
        if record is None:
            record = Category(name=body.key, user_id=user.id, is_default=False)
            session.add(record)
        # Presentation changes never rewrite financial history or another account's defaults.
        record.display_name = body.name if body.name != body.key else None
        record.icon = body.icon
        record.parent_name = body.parent_name
        for field in ['name_uz','name_ru']:
            if field in body.model_fields_set:setattr(record,field,getattr(body,field))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(409, "Bunday kategoriya mavjud.")
        return await category_catalog(session, user.id)

    @app.get("/api/summary")
    async def summary(start: date | None = None, end: date | None = None,
                      currency: str | None = Query(default=None,pattern=r"^[A-Z]{3}$"), account_id: int | None = Query(default=None,gt=0),
                      user: User = Depends(get_user), session: AsyncSession = Depends(get_session)):
        start, end = period(start, end)
        scoped, report_currency = await report_scope(session,user,currency,account_id)
        rows = (await session.execute(select(Transaction.date, Transaction.type, func.sum(Transaction.amount), func.count())
                .where(*scoped, Transaction.date >= start, Transaction.date <= end)
                .group_by(Transaction.date, Transaction.type).order_by(Transaction.date))).all()
        totals = {"income": Decimal(0), "expense": Decimal(0)}
        daily = {}
        count = 0
        for day, kind, amount, quantity in rows:
            if kind not in totals:
                continue
            totals[kind] += amount
            daily.setdefault(day.isoformat(), {"date": day.isoformat(), "income": "0", "expense": "0"})[kind] = str(amount)
            count += quantity
        all_time = (await session.execute(select(Transaction.type, func.sum(Transaction.amount))
                    .where(*scoped).group_by(Transaction.type))).all()
        balance = sum((amount if kind == "income" else -amount if kind == "expense" else Decimal(0)
                       for kind, amount in all_time), Decimal(0))
        from bot.services.finance import balance_adjustment
        balance += await balance_adjustment(session,user.id,report_currency,account_id)
        cats = (await session.execute(select(func.coalesce(Transaction.category, "Другое"), func.sum(Transaction.amount))
                .where(*scoped, Transaction.type == "expense", Transaction.date >= start, Transaction.date <= end)
                .group_by(Transaction.category).order_by(func.sum(Transaction.amount).desc()))).all()
        return {"currency": report_currency, "start": start, "end": end, "balance": str(balance),
                "income": str(totals["income"]), "expense": str(totals["expense"]), "count": count,
                "daily": list(daily.values()), "categories": [{"name": name, "amount": str(amount)} for name, amount in cats]}

    @app.get("/api/transactions")
    async def transactions(start: date | None = None, end: date | None = None,
                           search: str = Query("", max_length=100), kind: str = Query("", pattern="^(income|expense)?$"),
                           offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100),
                           currency: str | None = Query(default=None,pattern=r"^[A-Z]{3}$"), account_id: int | None = Query(default=None,gt=0),
                           user: User = Depends(get_user), session: AsyncSession = Depends(get_session)):
        start, end = period(start, end)
        scope,_ = await report_scope(session,user,currency,account_id)
        filters = [*scope, Transaction.date >= start, Transaction.date <= end]
        if kind:
            filters.append(Transaction.type == kind)
        if search:
            from sqlalchemy import or_
            filters.append(or_(Transaction.description.icontains(search, autoescape=True),
                               Transaction.category.icontains(search, autoescape=True)))
        total = (await session.execute(select(func.count()).select_from(Transaction).where(*filters))).scalar_one()
        items = (await session.execute(select(Transaction).where(*filters)
                 .order_by(Transaction.date.desc(), Transaction.id.desc()).offset(offset).limit(limit))).scalars().all()
        return {"items": [serialize_tx(tx) for tx in items], "total": total}

    @app.post("/api/transactions", status_code=201)
    async def create_transaction(body: TransactionInput, user: User = Depends(get_user),
                                 session: AsyncSession = Depends(get_session)):
        from bot.services.finance import owned_account, check_category, budget_status
        try:
            account=await owned_account(session,user,body.account_id)
            await check_category(session,user.id,body.category)
        except ValueError as error:raise HTTPException(409,str(error))
        item = Transaction(user_id=user.id, currency=account.currency, **{**body.model_dump(),"account_id":account.id})
        session.add(item)
        from bot.services.finance import budget_status
        await session.flush()
        await budget_status(session,user)
        await session.commit()
        return serialize_tx(item)

    @app.patch("/api/transactions/{transaction_id}")
    async def edit_transaction(transaction_id: int, body: TransactionInput, user: User = Depends(get_user),
                               session: AsyncSession = Depends(get_session)):
        item = (await session.execute(select(Transaction).where(Transaction.id == transaction_id,
                 Transaction.user_id==user.id).with_for_update())).scalar_one_or_none()
        if item is None:
            raise HTTPException(404, "Operatsiya topilmadi.")
        from bot.services.finance import owned_account, check_category
        try:
            account=await owned_account(session,user,body.account_id or item.account_id,item.currency)
            await check_category(session,user.id,body.category,item.category)
        except ValueError as error:raise HTTPException(409,str(error))
        for key, value in {**body.model_dump(),"account_id":account.id}.items():
            setattr(item, key, value)
        from bot.services.finance import budget_status
        await session.flush()
        await budget_status(session,user)
        await session.commit()
        return serialize_tx(item)

    @app.delete("/api/transactions/{transaction_id}", status_code=204)
    async def delete_transaction(transaction_id: int, user: User = Depends(get_user),
                                 session: AsyncSession = Depends(get_session)):
        result = await session.execute(delete(Transaction).where(Transaction.id == transaction_id, Transaction.user_id==user.id))
        if not result.rowcount:
            raise HTTPException(404, "Operatsiya topilmadi.")
        await session.commit()

    from api.finance import router as finance_router
    app.include_router(finance_router)
    from api.backup import router as backup_router
    app.include_router(backup_router)
    from api.exchange_rates import router as rates_router
    from bot.services.exchange_rates import ExchangeRateService
    app.state.exchange_rates = ExchangeRateService()
    app.include_router(rates_router)
    static = Path(__file__).resolve().parent.parent / "web" / "out"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="website")
    return app
