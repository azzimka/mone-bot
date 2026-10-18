import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.config import WebSettings
from api.main import create_app
from bot.models import Base, Transaction, User, WebLoginRequest, WebSession
from bot.services.web_auth import approve_login, digest

ORIGIN = "http://localhost:3000"


class WebApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.pool = async_sessionmaker(self.engine, expire_on_commit=False)
        config = WebSettings(DATABASE_URL="sqlite+aiosqlite://", WEB_PUBLIC_URL=ORIGIN,
                             TELEGRAM_BOT_USERNAME="mone_test_bot")
        self.app = create_app(config, self.pool)
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url=ORIGIN,
                                  headers={"Origin": ORIGIN})
        async with self.pool.begin() as session:
            self.user = User(telegram_id=111, first_name="Mirzo", default_currency="UZS")
            other = User(telegram_id=222, first_name="Other", default_currency="UZS")
            session.add_all([self.user, other])
            await session.flush()
            self.other_id = other.id
            entries = [
                Transaction(user_id=self.user.id, type="income", amount=Decimal("1000.50"), currency="UZS", category="Зарплата", date=date(2026, 10, 1)),
                Transaction(user_id=self.user.id, type="expense", amount=Decimal("25.25"), currency="UZS", category="Еда", description="Coffee 100%", date=date(2026, 10, 2)),
                Transaction(user_id=self.user.id, type="expense", amount=Decimal("100"), currency="USD", category="Еда", date=date(2026, 10, 2)),
                Transaction(user_id=other.id, type="expense", amount=Decimal("99999"), currency="UZS", category="Еда", date=date(2026, 10, 2)),
            ]
            session.add_all(entries)
            await session.flush()
            self.own_tx = entries[1].id
            self.foreign_tx = entries[3].id
            session.add(WebSession(token_hash=digest("test-session"), user_id=self.user.id,
                                   expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        self.client.cookies.set("mone_session", "test-session", path="/api")

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()

    def payload(self, **overrides):
        return {"type": "expense", "amount": "50.75", "date": "2026-10-03",
                "category": "Транспорт", "description": "Metro", **overrides}

    async def test_me_and_private_cache(self):
        result = await self.client.get("/api/me")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["first_name"], "Mirzo")
        self.assertEqual(result.headers["cache-control"], "no-store")

    async def test_anonymous_cannot_read_ledger(self):
        self.client.cookies.clear()
        for path in ("/api/me", "/api/summary", "/api/transactions", "/api/categories"):
            self.assertEqual((await self.client.get(path)).status_code, 401)

    async def test_summary_scopes_both_user_and_currency(self):
        result = (await self.client.get("/api/summary?start=2026-10-01&end=2026-10-31")).json()
        self.assertEqual(Decimal(result["income"]), Decimal("1000.50"))
        self.assertEqual(Decimal(result["expense"]), Decimal("25.25"))
        self.assertEqual(Decimal(result["balance"]), Decimal("975.25"))
        self.assertEqual(result["count"], 2)

    async def test_filters_and_literal_search(self):
        result = (await self.client.get("/api/transactions?start=2026-10-01&end=2026-10-31&kind=expense&search=100%25")).json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["id"], self.own_tx)

    async def test_period_validation_and_pagination_limits(self):
        for query in ("start=2026-10-31&end=2026-10-01", "limit=1000", "offset=-1", "kind=transfer"):
            self.assertEqual((await self.client.get(f"/api/transactions?{query}")).status_code, 422)

    async def test_create_uses_logged_in_owner_and_currency(self):
        result = await self.client.post("/api/transactions", json=self.payload())
        self.assertEqual(result.status_code, 201)
        async with self.pool() as session:
            saved = await session.get(Transaction, result.json()["id"])
            self.assertEqual(saved.user_id, self.user.id)
            self.assertEqual(saved.currency, "UZS")
            self.assertEqual(saved.amount, Decimal("50.75"))

    async def test_rejects_invalid_money_and_owner_override(self):
        for override in ({"amount": "-1"}, {"amount": "0"}, {"amount": "NaN"}, {"amount": "Infinity"},
                         {"amount": "1.001"}, {"amount": "99999999999999"}, {"category": "   "},
                         {"user_id": self.other_id}, {"currency": "USD"}):
            with self.subTest(override=override):
                self.assertEqual((await self.client.post("/api/transactions", json=self.payload(**override))).status_code, 422)

    async def test_other_users_transactions_cannot_be_changed(self):
        self.assertEqual((await self.client.patch(f"/api/transactions/{self.foreign_tx}", json=self.payload())).status_code, 404)
        self.assertEqual((await self.client.delete(f"/api/transactions/{self.foreign_tx}")).status_code, 404)

    async def test_edit_and_delete_own_transaction(self):
        result = await self.client.patch(f"/api/transactions/{self.own_tx}", json=self.payload(amount="12.50"))
        self.assertEqual(result.status_code, 200)
        self.assertEqual(Decimal(result.json()["amount"]), Decimal("12.50"))
        self.assertEqual((await self.client.delete(f"/api/transactions/{self.own_tx}")).status_code, 204)

    async def test_origin_required_for_all_mutations(self):
        for origin in ("https://attacker.example", "null", ""):
            result = await self.client.post("/api/transactions", json=self.payload(), headers={"Origin": origin})
            self.assertEqual(result.status_code, 403)

    async def test_login_needs_browser_secret_and_telegram_approval(self):
        self.client.cookies.clear()
        requested = await self.client.post("/api/auth/telegram/request")
        self.assertEqual(requested.status_code, 200)
        self.assertIn("httponly", requested.headers["set-cookie"].lower())
        request_id = requested.json()["url"].split("web_", 1)[1]
        self.assertEqual((await self.client.post("/api/auth/telegram/poll")).json()["status"], "pending")
        async with self.pool.begin() as session:
            self.assertTrue(await approve_login(session, request_id, self.user.id))
            self.assertFalse(await approve_login(session, request_id, self.other_id))
        # Knowing the Telegram link does not grant a browser session.
        async with AsyncClient(transport=ASGITransport(app=self.app), base_url=ORIGIN,
                               headers={"Origin": ORIGIN}, cookies={"mone_login": f"{request_id}.wrong"}) as stranger:
            self.assertEqual((await stranger.post("/api/auth/telegram/poll")).json()["status"], "expired")
            self.assertEqual((await stranger.get("/api/me")).status_code, 401)
        result = await self.client.post("/api/auth/telegram/poll")
        self.assertEqual(result.json()["status"], "approved")
        self.assertEqual((await self.client.get("/api/me")).json()["first_name"], "Mirzo")
        self.assertEqual((await self.client.post("/api/auth/telegram/poll")).json()["status"], "expired")
        async with self.pool() as session:
            sessions = (await session.execute(select(WebSession))).scalars().all()
            self.assertTrue(all(len(s.token_hash) == 64 for s in sessions))

    async def test_login_request_reuses_browser_request(self):
        first = await self.client.post("/api/auth/telegram/request")
        second = await self.client.post("/api/auth/telegram/request")
        self.assertEqual(first.json()["url"], second.json()["url"])

    async def test_expired_login_cannot_be_approved(self):
        requested = await self.client.post("/api/auth/telegram/request")
        request_id = requested.json()["url"].split("web_", 1)[1]
        async with self.pool.begin() as session:
            item = await session.get(WebLoginRequest, request_id)
            item.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        async with self.pool.begin() as session:
            self.assertFalse(await approve_login(session, request_id, self.user.id))
        self.assertEqual((await self.client.post("/api/auth/telegram/poll")).json()["status"], "expired")

    async def test_logout_revokes_session(self):
        self.assertEqual((await self.client.post("/api/auth/logout")).status_code, 204)
        self.client.cookies.set("mone_session", "test-session", path="/api")
        self.assertEqual((await self.client.get("/api/me")).status_code, 401)

    async def test_public_http_requires_https(self):
        with self.assertRaises(ValueError):
            WebSettings(DATABASE_URL="sqlite+aiosqlite://", WEB_PUBLIC_URL="http://mone.example")

    async def test_webapp_login_valid_and_invalid(self):
        import hashlib
        import hmac
        token = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
        self.app.state.bot_token = token
        auth_ts = int(datetime.now(timezone.utc).timestamp())
        data_str = f"auth_date={auth_ts}&user=%7B%22id%22%3A999%2C%22first_name%22%3A%22Azim%22%2C%22username%22%3A%22azim_test%22%7D"
        secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        data_check = f"auth_date={auth_ts}\nuser={{\"id\":999,\"first_name\":\"Azim\",\"username\":\"azim_test\"}}"
        valid_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

        # Valid TMA login
        res = await self.client.post("/api/auth/telegram/webapp", json={"init_data": f"{data_str}&hash={valid_hash}"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["user"]["first_name"], "Azim")
        self.assertTrue(len(body["token"]) > 20)

        # Invalid TMA login (bad hash)
        bad_res = await self.client.post("/api/auth/telegram/webapp", json={"init_data": f"{data_str}&hash=badhash123"})
        self.assertEqual(bad_res.status_code, 401)

