"""Telegram header authentication must honor the same expiry as session login."""
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import test_web_api


class TelegramAuthExpiryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_web_api.WebApiTests.asyncSetUp
    asyncTearDown = test_web_api.WebApiTests.asyncTearDown
    payload = test_web_api.WebApiTests.payload

    def signed_data(self, age: timedelta) -> str:
        token = "123456:synthetic-test-token"
        self.app.state.bot_token = token
        values = {
            "auth_date": str(int((datetime.now(timezone.utc) - age).timestamp())),
            "user": json.dumps({"id": 111, "first_name": "Mirzo"}, separators=(",", ":")),
        }
        check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return urlencode(values)

    async def test_expired_signed_data_cannot_read_or_write_through_header(self):
        self.client.cookies.clear()
        expired = self.signed_data(timedelta(days=4))
        headers = {"X-Telegram-Init-Data": expired}
        self.assertEqual((await self.client.get("/api/me", headers=headers)).status_code, 401)
        self.assertEqual((await self.client.post("/api/transactions", json=self.payload(), headers=headers)).status_code, 401)
        self.assertEqual((await self.client.post("/api/auth/telegram/webapp", json={"init_data": expired})).status_code, 401)

    async def test_recent_signed_data_remains_accepted_through_header(self):
        self.client.cookies.clear()
        headers = {"X-Telegram-Init-Data": self.signed_data(timedelta(hours=1))}
        profile = await self.client.get("/api/me", headers=headers)
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["first_name"], "Mirzo")
        created = await self.client.post("/api/transactions", json=self.payload(), headers=headers)
        self.assertEqual(created.status_code, 201, created.text)
