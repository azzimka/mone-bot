"""Tests for read-only AI financial advisor, SQL tools, prompt grounding, and bot mode."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

with patch.dict(
    "os.environ",
    {
        "TELEGRAM_BOT_TOKEN": "123456789:bot-test-token",
        "GROQ_API_KEY": "test-key",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    },
):
    from bot.handlers import advisor as advisor_handler
    from bot.handlers import commands
from bot.models import (
    Account,
    AdvisorMessage,
    Base,
    Budget,
    BudgetAlert,
    RecurringRule,
    Transaction,
    Transfer,
    User,
)
from bot.services.ai_advisor import (
    AIAdvisor,
    build_advisor_system_prompt,
    build_live_financial_snapshot,
    compute_live_accounts,
    format_telegram_html,
    split_telegram_message,
    strip_thinking,
    tool_analyze_spending_habits,
    tool_get_financial_overview,
    tool_query_transactions,
    tool_simulate_financial_decision,
)
from bot.services.exchange_rates import RateBook
from bot.services.finance import local_today
from bot.services.i18n import current_language
from bot.services.tts import (
    ElevenLabsTTSService,
    TTSNotConfiguredError,
    TTSSynthesisError,
    prepare_text_for_tts,
    strip_tts_tags,
)


class FakeRateService:
    def __init__(self, usd_uzs: Decimal = Decimal("12800")):
        self.book = RateBook(
            requested_date=date(2026, 11, 12),
            effective_date=date(2026, 11, 12),
            fetched_at=datetime.now(timezone.utc),
            rates={"UZS": Decimal(1), "USD": usd_uzs},
            stale=False,
        )

    async def get(self, session, requested=None):
        return self.book


class AIAdvisorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.pool = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = self.pool()

        self.user = User(
            telegram_id=1001,
            username="azim",
            first_name="Azim",
            default_currency="UZS",
            language="ru",
            timezone="Asia/Tashkent",
        )
        self.other = User(
            telegram_id=2002,
            username="other",
            first_name="Other",
            default_currency="UZS",
            language="ru",
        )
        self.session.add_all([self.user, self.other])
        await self.session.flush()

        today = local_today(self.user)
        self.today = today
        self.month_str = today.strftime("%Y-%m")

        self.uzs_acc = Account(
            user_id=self.user.id,
            name="Uzcard",
            kind="card",
            currency="UZS",
            opening_balance=Decimal("1000000"),
        )
        self.usd_acc = Account(
            user_id=self.user.id,
            name="Dollar Cash",
            kind="cash",
            currency="USD",
            opening_balance=Decimal("200"),
        )
        self.other_acc = Account(
            user_id=self.other.id,
            name="Other Card",
            kind="card",
            currency="UZS",
            opening_balance=Decimal("9999999"),
        )
        self.session.add_all([self.uzs_acc, self.usd_acc, self.other_acc])
        await self.session.flush()

        # Ledger entries for user + isolated entry for other user
        self.tx_income = Transaction(
            user_id=self.user.id,
            account_id=self.uzs_acc.id,
            type="income",
            amount=Decimal("5000000"),
            currency="UZS",
            category="Зарплата",
            description="Аванс",
            date=today.replace(day=1),
        )
        self.tx_coffee_1 = Transaction(
            user_id=self.user.id,
            account_id=self.uzs_acc.id,
            type="expense",
            amount=Decimal("30000"),
            currency="UZS",
            category="Еда",
            description="Кофе",
            date=today,
        )
        self.tx_coffee_2 = Transaction(
            user_id=self.user.id,
            account_id=self.uzs_acc.id,
            type="expense",
            amount=Decimal("35000"),
            currency="UZS",
            category="Еда",
            description="Кофе",
            date=today,
        )
        self.tx_taxi = Transaction(
            user_id=self.user.id,
            account_id=self.uzs_acc.id,
            type="expense",
            amount=Decimal("45000"),
            currency="UZS",
            category="Транспорт",
            description="Яндекс Такси",
            date=today,
        )
        # Reconcile entry should adjust account balance but NOT be counted as real expense
        self.tx_reconcile = Transaction(
            user_id=self.user.id,
            account_id=self.uzs_acc.id,
            type="expense",
            amount=Decimal("90000"),
            currency="UZS",
            category="Сверка",
            description="Сверка баланса",
            date=today,
        )
        self.tx_other = Transaction(
            user_id=self.other.id,
            account_id=self.other_acc.id,
            type="expense",
            amount=Decimal("888888"),
            currency="UZS",
            category="Еда",
            description="Чужая трата",
            date=today,
        )
        self.session.add_all(
            [self.tx_income, self.tx_coffee_1, self.tx_coffee_2, self.tx_taxi, self.tx_reconcile, self.tx_other]
        )

        # Budget >= 80% spent would insert BudgetAlert if create_alerts=True; verify advisor keeps it read-only
        self.budget = Budget(
            user_id=self.user.id,
            month=self.month_str,
            category="Еда",
            currency="UZS",
            amount=Decimal("70000"),
            notify_telegram=True,
        )
        # Recurring expense due soon within 30 days
        self.rule = RecurringRule(
            user_id=self.user.id,
            account_id=self.uzs_acc.id,
            type="expense",
            amount=Decimal("200000"),
            category="Связь",
            description="Интернет",
            frequency="monthly",
            next_date=today + timedelta(days=5),
            anchor_day=min(28, today.day),
            enabled=True,
        )
        self.session.add_all([self.budget, self.rule])
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def _ledger_counts(self) -> dict[str, int]:
        models = {
            "users": User,
            "accounts": Account,
            "transactions": Transaction,
            "transfers": Transfer,
            "budgets": Budget,
            "budget_alerts": BudgetAlert,
            "recurring_rules": RecurringRule,
        }
        counts = {}
        for name, model in models.items():
            counts[name] = (await self.session.execute(select(func.count()).select_from(model))).scalar_one()
        return counts

    async def test_snapshot_and_tools_are_strictly_read_only_and_accurate(self):
        before_counts = await self._ledger_counts()
        rates = FakeRateService(usd_uzs=Decimal("12800"))

        accounts = await compute_live_accounts(self.session, self.user)
        # Uzcard: 1,000,000 + 5,000,000 - 30,000 - 35,000 - 45,000 - 90,000 = 5,800,000 UZS
        uzcard = next(a for a in accounts if a["name"] == "Uzcard")
        self.assertEqual(uzcard["balance"], "5800000")
        self.assertEqual(len(accounts), 2)  # Never leaks self.other's account

        snapshot = await build_live_financial_snapshot(self.session, self.user, rate_service=rates)
        self.assertEqual(snapshot["current_month_cashflow"]["income"]["by_currency"]["UZS"], "5000000")
        # Real expense excludes Сверка (30k + 35k + 45k = 110,000 UZS)
        self.assertEqual(snapshot["current_month_cashflow"]["expense"]["by_currency"]["UZS"], "110000")
        # Liquid default equivalent: 5,800,000 + 200 * 12,800 = 8,360,000 UZS
        self.assertEqual(snapshot["total_liquid_balances"]["equivalent_in_default_currency"], "8360000")
        self.assertEqual(len(snapshot["budgets_this_month"]), 1)

        overview = await tool_get_financial_overview(self.session, self.user, rates, period_days=30)
        self.assertEqual(overview["selected_period"]["expense"]["by_currency"]["UZS"], "110000")

        queried = await tool_query_transactions(self.session, self.user, search="Кофе")
        self.assertEqual(queried["total_matching_count"], 2)
        self.assertEqual(queried["totals_by_type_and_currency"]["expense"]["UZS"], "65000")

        habits_desc = await tool_analyze_spending_habits(self.session, self.user, group_by="description")
        coffee_row = next(r for r in habits_desc["breakdown"] if r["group"] == "Кофе")
        self.assertEqual(coffee_row["tx_count"], 2)
        self.assertEqual(coffee_row["total_amount"], "65000")
        self.assertFalse(any(r["group"] == "Сверка баланса" for r in habits_desc["breakdown"]))

        sim = await tool_simulate_financial_decision(
            self.session,
            self.user,
            rates,
            amount=100,
            currency="USD",
            horizon_days=30,
        )
        self.assertEqual(sim["balance_in_target_currency_before"], "200")
        self.assertEqual(sim["balance_in_target_currency_after"], "100")
        self.assertEqual(sim["purchase_equivalent_default"], "1280000")
        # Total liquid after 100 USD (1,280,000 UZS) = 8,360,000 - 1,280,000 = 7,080,000
        self.assertEqual(sim["total_liquid_default_after_purchase"], "7080000")
        # Upcoming recurring 200,000 UZS deducted from free default cash -> 6,880,000
        self.assertEqual(sim["free_default_after_purchase_and_recurring"], "6880000")

        after_counts = await self._ledger_counts()
        self.assertEqual(before_counts, after_counts)
        self.assertEqual(after_counts["budget_alerts"], 0)

    async def test_live_changes_reflected_immediately(self):
        rates = FakeRateService()
        snap1 = await build_live_financial_snapshot(self.session, self.user, rate_service=rates)
        self.assertEqual(snap1["current_month_cashflow"]["expense"]["by_currency"]["UZS"], "110000")

        # User adds a transaction and deletes one -> advisor sees changes immediately
        new_tx = Transaction(
            user_id=self.user.id,
            account_id=self.uzs_acc.id,
            type="expense",
            amount=Decimal("200000"),
            currency="UZS",
            category="Одежда",
            description="Куртка",
            date=self.today,
        )
        self.session.add(new_tx)
        await self.session.delete(self.tx_taxi)
        await self.session.commit()

        snap2 = await build_live_financial_snapshot(self.session, self.user, rate_service=rates)
        # 110,000 - 45,000 + 200,000 = 265,000
        self.assertEqual(snap2["current_month_cashflow"]["expense"]["by_currency"]["UZS"], "265000")
        uzcard = next(a for a in snap2["accounts"] if a["name"] == "Uzcard")
        # 5,800,000 + 45,000 - 200,000 = 5,645,000
        self.assertEqual(uzcard["balance"], "5645000")

    async def test_system_prompt_contains_methodology_and_read_only_rules(self):
        snapshot = await build_live_financial_snapshot(self.session, self.user, rate_service=FakeRateService())
        prompt = build_advisor_system_prompt(self.user, snapshot)
        self.assertIn("СТИЛЬ ОБЩЕНИЯ И ПРОСТОТА", prompt)
        self.assertIn("КАК СТРОИТЬ ОТВЕТ", prompt)
        self.assertIn("ТОЛЬКО ЧТЕНИЕ", prompt)
        self.assertIn("10–15-летний подросток", prompt)
        self.assertIn("Uzcard", prompt)

    async def test_advisor_tool_call_loop_and_history(self):
        before_counts = await self._ledger_counts()

        tool_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="simulate_financial_decision",
                arguments=json.dumps({"amount": 500000, "currency": "UZS"}),
            ),
        )
        resp_tool = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[tool_call]))]
        )
        resp_final = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="<think>internal reasoning</think>**Вывод:** покупку на 500 000 UZS можно сделать без риска.",
                        tool_calls=[],
                    )
                )
            ]
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [resp_tool, resp_final]

        advisor = AIAdvisor(api_key="test-key", rate_service=FakeRateService(), client=mock_client)
        reply = await advisor.ask(self.session, self.user, "Могу ли я купить кроссовки за 500 тысяч?")

        self.assertEqual(reply, "**Вывод:** покупку на 500 000 UZS можно сделать без риска.")
        self.assertEqual(mock_client.chat.completions.create.call_count, 2)

        # Second turn passes tool result in messages
        second_call_msgs = mock_client.chat.completions.create.call_args_list[1].kwargs["messages"]
        tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        tool_payload = json.loads(tool_msgs[0]["content"])
        self.assertEqual(tool_payload["purchase_amount"], "500000")

        history = await advisor.get_history(self.session, self.user.id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "user")
        self.assertEqual(history[1]["role"], "assistant")

        # Ledger untouched
        self.assertEqual(before_counts, await self._ledger_counts())

        # Clear dialog only removes advisor_messages
        deleted = await advisor.clear_history(self.session, self.user.id)
        self.assertEqual(deleted, 2)
        self.assertEqual(await advisor.get_history(self.session, self.user.id), [])
        self.assertEqual(before_counts, await self._ledger_counts())

    async def test_formatting_and_bot_fsm_mode(self):
        self.assertEqual(strip_thinking("<think>abc</think>Привет"), "Привет")
        formatted = format_telegram_html("**Важно:** <100> & `500 UZS`")
        self.assertEqual(formatted, "<b>Важно:</b> &lt;100&gt; &amp; <code>500 UZS</code>")
        chunks = split_telegram_message(("строка\n" * 800), limit=500)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertGreater(len(chunks), 1)

        # Verify main keyboard includes AI-financier button in RU & UZ
        token_ru = current_language.set("ru")
        try:
            kb_ru = commands.get_main_keyboard()
            texts_ru = [btn.text for row in kb_ru.keyboard for btn in row]
            self.assertIn("🧠 AI-финансист", texts_ru)
        finally:
            current_language.reset(token_ru)

        token_uz = current_language.set("uz")
        try:
            kb_uz = commands.get_main_keyboard()
            texts_uz = [btn.text for row in kb_uz.keyboard for btn in row]
            self.assertIn("🧠 AI-moliyachi", texts_uz)
        finally:
            current_language.reset(token_uz)

        # Verify FSM state transitions
        storage = MemoryStorage()
        fsm = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=1001, user_id=1001))
        msg = MagicMock()
        msg.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
        msg.answer = AsyncMock()

        await advisor_handler.enter_advisor_mode(msg, fsm, self.session)
        self.assertEqual(await fsm.get_state(), advisor_handler.AdvisorStates.chatting.state)
        msg.answer.assert_awaited_once()
        intro_text = msg.answer.call_args.args[0]
        self.assertIn("Режим AI-финансиста включён", intro_text)
        self.assertNotIn("только к чтению и анализу", intro_text)

        msg.answer.reset_mock()
        await advisor_handler.exit_advisor_mode(msg, fsm)
        self.assertIsNone(await fsm.get_state())
        msg.answer.assert_awaited_once()

    async def test_tts_cleaning_zero_cost_when_unconfigured_and_concurrency_cap(self):
        cleaned = prepare_text_for_tts(
            "<think>secret</think>[confident] **Вывод:** траты ≈ `50 000` [сум] ≤ 100 000 🧠 https://example.com. [serious] Второе предложение.",
            max_chars=180,
        )
        self.assertNotIn("<think>", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("≈", cleaned)
        self.assertNotIn("≤", cleaned)
        self.assertIn("около 50 000", cleaned)
        self.assertIn("не больше 100 000", cleaned)
        self.assertIn("[confident]", cleaned)
        self.assertIn("[serious]", cleaned)
        self.assertNotIn("[сум]", cleaned)
        self.assertEqual(strip_tts_tags("[confident] Отлично. [warmly] Продолжаем."), "Отлично. Продолжаем.")

        # Unconfigured TTS never makes network calls
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        unconfigured = ElevenLabsTTSService(api_key="", http_client=mock_http)
        self.assertFalse(unconfigured.is_configured)
        with self.assertRaises(TTSNotConfiguredError):
            await unconfigured.synthesize("Привет")
        mock_http.post.assert_not_called()

        # Concurrent requests respect max_concurrency=2 and zero double-billing retries
        in_flight = 0
        peak_in_flight = 0
        post_calls = 0
        captured_payloads = []

        async def fake_post(url, params=None, headers=None, json=None):
            nonlocal in_flight, peak_in_flight, post_calls
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)
            post_calls += 1
            captured_payloads.append(json)
            await asyncio.sleep(0.02)
            in_flight -= 1
            return httpx.Response(200, content=b"OggS-fake-opus-bytes")

        pooled_http = AsyncMock(spec=httpx.AsyncClient)
        pooled_http.post.side_effect = fake_post
        pooled_http.is_closed = False
        tts = ElevenLabsTTSService(
            api_key="el-test-key",
            max_concurrency=2,
            max_chars=500,
            http_client=pooled_http,
        )
        self.assertEqual(tts.model_id, "eleven_v4_turbo")
        self.assertEqual(tts.voice_id, "nPczCjzI2devNBz1zQrb")
        results = await asyncio.gather(*(tts.synthesize(f"[confident] Ответ номер {i}") for i in range(6)))
        self.assertEqual(len(results), 6)
        self.assertTrue(all(r == b"OggS-fake-opus-bytes" for r in results))
        self.assertLessEqual(peak_in_flight, 2)
        self.assertEqual(post_calls, 6)
        self.assertEqual(captured_payloads[0]["voice_settings"], {"stability": 0.4, "similarity_boost": 0.78})

        # Error from ElevenLabs is raised immediately with NO blind retry
        err_http = AsyncMock(spec=httpx.AsyncClient)
        err_http.post.return_value = httpx.Response(429, content=b"rate limited")
        err_http.is_closed = False
        tts_err = ElevenLabsTTSService(api_key="el-test-key", http_client=err_http)
        with self.assertRaises(TTSSynthesisError):
            await tts_err.synthesize("Проверка")
        self.assertEqual(err_http.post.call_count, 1)

    async def test_advisor_empty_primary_falls_back_and_voice_prompt_mode(self):
        # Empty response from primary model triggers clean fallback to next model
        resp_empty = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[]))])
        resp_ok = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="[confident] Баланс стабильный, траты в норме.", tool_calls=[]))]
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = [resp_empty, resp_ok]

        advisor = AIAdvisor(api_key="test-key", rate_service=FakeRateService(), client=mock_client)
        reply = await advisor.ask(
            self.session,
            self.user,
            "Как дела с бюджетом?",
            response_mode="voice",
            detail_level="brief",
        )
        self.assertEqual(reply, "[confident] Баланс стабильный, траты в норме.")
        # History stays clean without inline TTS tags so later text turns don't mimic them
        history = await advisor.get_history(self.session, self.user.id)
        self.assertEqual(history[-1]["content"], "Баланс стабильный, траты в норме.")
        self.assertEqual(mock_client.chat.completions.create.call_count, 2)
        first_call = mock_client.chat.completions.create.call_args_list[0].kwargs
        second_call = mock_client.chat.completions.create.call_args_list[1].kwargs
        self.assertEqual(first_call["model"], "openai/gpt-oss-120b")
        self.assertEqual(second_call["model"], "qwen/qwen3.8-27b")
        self.assertEqual(first_call["max_tokens"], 1600)
        self.assertIn("ФОРМАТ ОЗВУЧКИ", first_call["messages"][0]["content"])
        self.assertIn("350–500 символов", first_call["messages"][0]["content"])

    async def test_format_choice_buttons_double_click_guard_and_tts_gating(self):
        advisor_handler.pending_advisor_questions.clear()
        advisor_handler.processing_advisor_questions.clear()
        advisor_handler.active_advisor_users.clear()

        storage = MemoryStorage()
        fsm = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=1001, user_id=1001))
        await fsm.set_state(advisor_handler.AdvisorStates.chatting)

        msg = MagicMock()
        msg.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
        msg.chat = SimpleNamespace(id=1001)
        msg.text = "Стоит ли брать новый ноутбук?"
        msg.answer = AsyncMock()

        fake_advisor = MagicMock()
        fake_advisor.ask = AsyncMock(return_value="Да, остаток позволяет взять ноутбук без риска.")
        fake_tts = MagicMock()
        fake_tts.synthesize = AsyncMock(return_value=b"OggS-voice-payload")
        fake_bot = MagicMock()
        fake_bot.send_chat_action = AsyncMock()

        with (
            patch.object(advisor_handler, "ai_advisor", fake_advisor),
            patch.object(advisor_handler, "tts_service", fake_tts),
        ):
            # Step 0: sending question asks voice/text (ZERO LLM or TTS calls!)
            await advisor_handler.advisor_text_question(msg)
            fake_advisor.ask.assert_not_called()
            fake_tts.synthesize.assert_not_called()
            msg.answer.assert_awaited_once()
            fmt_buttons = msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0]
            self.assertEqual([b.text for b in fmt_buttons], ["🎙 Голосом", "📝 Текстом"])
            text_cb_data = fmt_buttons[1].callback_data

            # Step 1: selecting 📝 Текстом asks brief/detailed (STILL ZERO LLM or TTS calls!)
            cb_msg_text = MagicMock()
            cb_msg_text.chat = SimpleNamespace(id=1001)
            cb_msg_text.edit_text = AsyncMock()
            cb_msg_text.delete = AsyncMock()
            cb_msg_text.answer = AsyncMock()
            cb_msg_text.answer_voice = AsyncMock()

            cb_fmt_text = MagicMock()
            cb_fmt_text.data = text_cb_data
            cb_fmt_text.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
            cb_fmt_text.message = cb_msg_text
            cb_fmt_text.answer = AsyncMock()

            await advisor_handler.on_advisor_format_selected(cb_fmt_text)
            fake_advisor.ask.assert_not_called()
            fake_tts.synthesize.assert_not_called()
            cb_msg_text.edit_text.assert_awaited_once()
            self.assertEqual(cb_msg_text.edit_text.call_args.args[0], "Как вам ответить?")
            len_buttons = cb_msg_text.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0]
            self.assertEqual([b.text for b in len_buttons], ["⚡ По делу", "📖 Подробно"])
            brief_text_cb = len_buttons[0].callback_data

            # Step 2a: selecting ⚡ По делу -> calls LLM in brief text mode, ZERO TTS calls
            cb_len_text = MagicMock()
            cb_len_text.data = brief_text_cb
            cb_len_text.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
            cb_len_text.message = cb_msg_text
            cb_len_text.answer = AsyncMock()

            await advisor_handler.on_advisor_detail_selected(cb_len_text, fake_bot, fsm, self.session)
            fake_advisor.ask.assert_awaited_once()
            self.assertEqual(fake_advisor.ask.call_args.kwargs["response_mode"], "text")
            self.assertEqual(fake_advisor.ask.call_args.kwargs["detail_level"], "brief")
            fake_tts.synthesize.assert_not_called()
            cb_msg_text.answer.assert_awaited_once()
            cb_msg_text.answer_voice.assert_not_called()

            # Step 2b: selecting 🎙 Голосом -> 📖 Подробно twice concurrently -> runs LLM & TTS ONCE!
            fake_advisor.ask.reset_mock()
            fake_tts.synthesize.reset_mock()
            msg.answer.reset_mock()
            await advisor_handler.advisor_text_question(msg)
            voice_fmt_cb = msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data

            cb_msg_voice = MagicMock()
            cb_msg_voice.chat = SimpleNamespace(id=1001)
            cb_msg_voice.edit_text = AsyncMock()
            cb_msg_voice.edit_reply_markup = AsyncMock()
            cb_msg_voice.delete = AsyncMock()
            cb_msg_voice.answer = AsyncMock()
            cb_msg_voice.answer_voice = AsyncMock()

            cb_fmt_voice = MagicMock()
            cb_fmt_voice.data = voice_fmt_cb
            cb_fmt_voice.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
            cb_fmt_voice.message = cb_msg_voice
            cb_fmt_voice.answer = AsyncMock()
            await advisor_handler.on_advisor_format_selected(cb_fmt_voice)
            detailed_voice_cb = cb_msg_voice.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0][1].callback_data

            cb_voice_1 = MagicMock()
            cb_voice_1.data = detailed_voice_cb
            cb_voice_1.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
            cb_voice_1.message = cb_msg_voice
            cb_voice_1.answer = AsyncMock()

            cb_voice_2 = MagicMock()
            cb_voice_2.data = detailed_voice_cb
            cb_voice_2.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
            cb_voice_2.message = cb_msg_voice
            cb_voice_2.answer = AsyncMock()

            await asyncio.gather(
                advisor_handler.on_advisor_detail_selected(cb_voice_1, fake_bot, fsm, self.session),
                advisor_handler.on_advisor_detail_selected(cb_voice_2, fake_bot, fsm, self.session),
            )
            self.assertEqual(fake_advisor.ask.await_count, 1)
            self.assertEqual(fake_advisor.ask.call_args.kwargs["response_mode"], "voice")
            self.assertEqual(fake_advisor.ask.call_args.kwargs["detail_level"], "detailed")
            self.assertEqual(fake_tts.synthesize.await_count, 1)
            self.assertEqual(
                fake_tts.synthesize.call_args.kwargs["max_chars"],
                advisor_handler.settings.ELEVENLABS_MAX_CHARS,
            )
            cb_msg_voice.answer_voice.assert_awaited_once()

            # Step 2c: brief voice sets tight 750-char TTS cap and error falls back smoothly to text
            fake_advisor.ask.reset_mock()
            fake_tts.synthesize.reset_mock()
            fake_tts.synthesize.side_effect = TTSNotConfiguredError("no key")
            msg.answer.reset_mock()
            await advisor_handler.advisor_text_question(msg)
            voice_fmt_2 = msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data

            cb_msg_fb = MagicMock()
            cb_msg_fb.chat = SimpleNamespace(id=1001)
            cb_msg_fb.edit_text = AsyncMock()
            cb_msg_fb.delete = AsyncMock()
            cb_msg_fb.answer = AsyncMock()
            cb_msg_fb.answer_voice = AsyncMock()
            cb_fmt_fb = MagicMock()
            cb_fmt_fb.data = voice_fmt_2
            cb_fmt_fb.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
            cb_fmt_fb.message = cb_msg_fb
            cb_fmt_fb.answer = AsyncMock()
            await advisor_handler.on_advisor_format_selected(cb_fmt_fb)
            brief_voice_cb = cb_msg_fb.edit_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data

            cb_fb = MagicMock()
            cb_fb.data = brief_voice_cb
            cb_fb.from_user = SimpleNamespace(id=self.user.telegram_id, username="azim", first_name="Azim")
            cb_fb.message = cb_msg_fb
            cb_fb.answer = AsyncMock()

            await advisor_handler.on_advisor_detail_selected(cb_fb, fake_bot, fsm, self.session)
            self.assertEqual(fake_tts.synthesize.call_args.kwargs["max_chars"], 750)
            cb_msg_fb.answer_voice.assert_not_called()
            self.assertEqual(cb_msg_fb.answer.await_count, 2)
