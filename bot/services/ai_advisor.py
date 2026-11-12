"""Read-only AI financial advisor backed by live ledger queries and Groq tool calling."""

from __future__ import annotations

import asyncio
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import html
import inspect
import json
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

from groq import AsyncGroq, Groq
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import (
    Account,
    AdvisorMessage,
    RecurringRule,
    Transaction,
    Transfer,
    User,
)
from bot.services.exchange_rates import ExchangeRateService, RateBook, RatesUnavailable, money_round
from bot.services.finance import budget_status, local_today
from bot.services.tts import strip_tts_tags

logger = logging.getLogger(__name__)

PRIMARY_ADVISOR_MODEL = "openai/gpt-oss-120b"
FALLBACK_ADVISOR_MODEL = "qwen/qwen3.8-27b"
TERTIARY_ADVISOR_MODEL = "openai/gpt-oss-20b"
RECONCILE_CATEGORY = "Сверка"
MAX_TOOL_ROUNDS = 4
MAX_HISTORY_TURNS = 12

WEEKDAY_NAMES_RU = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]


def _dec_str(value: Decimal | int | float) -> str:
    d = Decimal(str(value))
    normalized = d.quantize(Decimal("0.01")) if d != d.to_integral_value() else d
    s = format(normalized, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _parse_date(raw: str | None, default: date | None = None) -> date | None:
    if not raw:
        return default
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return default


def strip_thinking(text: str) -> str:
    """Remove model reasoning tags if emitted inline."""
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def format_telegram_html(text: str) -> str:
    """Convert lightweight Markdown (**bold**, `code`) into crash-proof Telegram HTML."""
    escaped = html.escape(text)
    escaped = re.sub(r"```(?:[a-zA-Z0-9_-]+\n)?(.*?)```", r"<pre>\1</pre>", escaped, flags=re.DOTALL)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^\*\n]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?m)^#{1,4}\s+(.+)$", r"<b>\1</b>", escaped)
    return escaped.strip()


def split_telegram_message(text: str, limit: int = 3900) -> list[str]:
    """Split long advisor responses along line boundaries within Telegram limits."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append("".join(current).rstrip())
                current, current_len = [], 0
            for start in range(0, len(line), limit):
                chunks.append(line[start : start + limit])
            continue
        if current_len + len(line) > limit and current:
            chunks.append("".join(current).rstrip())
            current, current_len = [], 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current).rstrip())
    return chunks or [text[:limit]]


async def compute_live_accounts(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Compute exact balances per account strictly via SELECT (zero DB writes)."""
    accounts = (
        await session.execute(
            select(Account).where(Account.user_id == user.id).order_by(Account.id)
        )
    ).scalars().all()

    tx_rows = (
        await session.execute(
            select(Transaction.account_id, Transaction.currency, Transaction.type, func.sum(Transaction.amount))
            .where(Transaction.user_id == user.id)
            .group_by(Transaction.account_id, Transaction.currency, Transaction.type)
        )
    ).all()

    transfers = (
        await session.execute(select(Transfer).where(Transfer.user_id == user.id))
    ).scalars().all()

    transfer_in: dict[int, Decimal] = defaultdict(Decimal)
    transfer_out: dict[int, Decimal] = defaultdict(Decimal)
    for tr in transfers:
        transfer_in[tr.destination_id] += tr.destination_amount
        transfer_out[tr.source_id] += tr.source_amount

    by_account: dict[int | None, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    unassigned_by_currency: dict[str, Decimal] = defaultdict(Decimal)
    for account_id, currency, kind, total in tx_rows:
        delta = total if kind == "income" else -total if kind == "expense" else Decimal(0)
        if account_id is None:
            unassigned_by_currency[currency] += delta
        else:
            by_account[account_id][currency] += delta

    result: list[dict[str, Any]] = []
    for account in accounts:
        tx_net = by_account[account.id].get(account.currency, Decimal(0))
        bal = account.opening_balance + tx_net + transfer_in[account.id] - transfer_out[account.id]
        result.append(
            {
                "id": account.id,
                "name": account.name,
                "kind": account.kind,
                "currency": account.currency,
                "balance": _dec_str(bal),
                "opening_balance": _dec_str(account.opening_balance),
                "archived": bool(account.archived),
            }
        )

    for currency, delta in sorted(unassigned_by_currency.items()):
        if delta != 0:
            result.append(
                {
                    "id": None,
                    "name": f"Без счёта ({currency})",
                    "kind": "unassigned",
                    "currency": currency,
                    "balance": _dec_str(delta),
                    "opening_balance": "0",
                    "archived": False,
                }
            )
    return result


async def _safe_rate_book(
    session: AsyncSession,
    rate_service: ExchangeRateService | None,
) -> RateBook | None:
    if rate_service is None:
        return None
    try:
        return await rate_service.get(session)
    except Exception as exc:
        logger.info("Advisor proceeding without CBU rates (%s)", type(exc).__name__)
        return None


def _convert_totals(
    totals_by_currency: dict[str, Decimal],
    target_currency: str,
    rates: RateBook | None,
) -> dict[str, Any]:
    by_ccy = {ccy: _dec_str(val) for ccy, val in sorted(totals_by_currency.items())}
    converted: Decimal | None = Decimal(0)
    missing: list[str] = []
    for ccy, val in totals_by_currency.items():
        if ccy == target_currency:
            if converted is not None:
                converted += val
        elif rates is not None and ccy in rates.rates and target_currency in rates.rates:
            if converted is not None:
                converted += money_round(rates.convert(val, ccy, target_currency))
        else:
            missing.append(ccy)
            converted = None
    return {
        "by_currency": by_ccy,
        "equivalent_in_default_currency": _dec_str(converted) if converted is not None else None,
        "default_currency": target_currency,
        "unconverted_currencies": missing,
    }


async def _cashflow_summary(
    session: AsyncSession,
    user: User,
    start_date: date,
    end_date: date,
    rates: RateBook | None,
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Transaction.type, Transaction.currency, Transaction.category, Transaction.amount)
            .where(
                Transaction.user_id == user.id,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
        )
    ).all()

    income_ccy: dict[str, Decimal] = defaultdict(Decimal)
    expense_ccy: dict[str, Decimal] = defaultdict(Decimal)
    reconcile_ccy: dict[str, Decimal] = defaultdict(Decimal)
    cat_totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    cat_counts: dict[tuple[str, str], int] = defaultdict(int)
    tx_count = 0

    for kind, ccy, category, amount in rows:
        tx_count += 1
        cat = category or "Другое"
        if cat == RECONCILE_CATEGORY:
            delta = amount if kind == "income" else -amount if kind == "expense" else Decimal(0)
            reconcile_ccy[ccy] += delta
            continue
        if kind == "income":
            income_ccy[ccy] += amount
        elif kind == "expense":
            expense_ccy[ccy] += amount
            cat_totals[(cat, ccy)] += amount
            cat_counts[(cat, ccy)] += 1

    days_in_window = max(1, (end_date - start_date).days + 1)
    top_by_amount = sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
    top_by_frequency = sorted(
        cat_counts.items(),
        key=lambda kv: (kv[1], cat_totals[kv[0]]),
        reverse=True,
    )[:6]

    inc_conv = _convert_totals(income_ccy, user.default_currency, rates)
    exp_conv = _convert_totals(expense_ccy, user.default_currency, rates)
    net_default = None
    savings_rate_pct = None
    daily_burn_default = None
    if inc_conv["equivalent_in_default_currency"] is not None and exp_conv["equivalent_in_default_currency"] is not None:
        inc_d = Decimal(inc_conv["equivalent_in_default_currency"])
        exp_d = Decimal(exp_conv["equivalent_in_default_currency"])
        net_d = inc_d - exp_d
        net_default = _dec_str(net_d)
        daily_burn_default = _dec_str(money_round(exp_d / Decimal(days_in_window)))
        if inc_d > 0:
            savings_rate_pct = _dec_str(money_round((net_d / inc_d) * Decimal(100)))

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days": days_in_window,
        "transaction_count": tx_count,
        "income": inc_conv,
        "expense": exp_conv,
        "reconcile_adjustments_by_currency": {k: _dec_str(v) for k, v in reconcile_ccy.items() if v != 0},
        "net_in_default_currency": net_default,
        "savings_rate_pct": savings_rate_pct,
        "avg_daily_expense_default": daily_burn_default,
        "top_expense_categories_by_amount": [
            {
                "category": cat,
                "currency": ccy,
                "amount": _dec_str(amt),
                "count": cat_counts[(cat, ccy)],
            }
            for (cat, ccy), amt in top_by_amount
        ],
        "top_expense_categories_by_frequency": [
            {
                "category": cat,
                "currency": ccy,
                "count": cnt,
                "amount": _dec_str(cat_totals[(cat, ccy)]),
                "avg_ticket": _dec_str(money_round(cat_totals[(cat, ccy)] / Decimal(cnt))),
            }
            for (cat, ccy), cnt in top_by_frequency
        ],
    }


async def build_live_financial_snapshot(
    session: AsyncSession,
    user: User,
    rate_service: ExchangeRateService | None = None,
) -> dict[str, Any]:
    """Assemble a fresh, strictly read-only financial snapshot directly from the DB."""
    today = local_today(user)
    month_start = today.replace(day=1)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    month_end = today.replace(day=days_in_month)
    month_str = today.strftime("%Y-%m")
    prev_month_end = month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)

    rates = await _safe_rate_book(session, rate_service)
    accounts = await compute_live_accounts(session, user)

    active_balances_ccy: dict[str, Decimal] = defaultdict(Decimal)
    for acc in accounts:
        if not acc["archived"]:
            active_balances_ccy[acc["currency"]] += Decimal(acc["balance"])
    liquidity = _convert_totals(active_balances_ccy, user.default_currency, rates)

    current_month_flow = await _cashflow_summary(session, user, month_start, today, rates)
    previous_month_flow = await _cashflow_summary(session, user, prev_month_start, prev_month_end, rates)

    # Read-only budget status (create_alerts=False guarantees zero inserts)
    budgets = await budget_status(session, user, month=month_str, create_alerts=False)
    month_elapsed_pct = money_round(Decimal(today.day) / Decimal(days_in_month) * Decimal(100))

    # Active recurring rules
    rules = (
        await session.execute(
            select(RecurringRule)
            .where(RecurringRule.user_id == user.id, RecurringRule.enabled.is_(True))
            .order_by(RecurringRule.next_date)
        )
    ).scalars().all()
    acc_name_by_id = {acc["id"]: acc for acc in accounts if acc["id"] is not None}
    recurring_list = []
    upcoming_recurring_expense_ccy: dict[str, Decimal] = defaultdict(Decimal)
    for rule in rules:
        acc_info = acc_name_by_id.get(rule.account_id, {})
        ccy = acc_info.get("currency", user.default_currency)
        if rule.type == "expense" and rule.next_date <= month_end:
            upcoming_recurring_expense_ccy[ccy] += rule.amount
        recurring_list.append(
            {
                "id": rule.id,
                "type": rule.type,
                "amount": _dec_str(rule.amount),
                "currency": ccy,
                "account": acc_info.get("name", ""),
                "category": rule.category,
                "description": rule.description,
                "frequency": rule.frequency,
                "next_date": rule.next_date.isoformat(),
            }
        )

    # Last 10 transactions so edits/deletions/additions are always immediately reflected
    recent_txs = (
        await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user.id)
            .order_by(Transaction.date.desc(), Transaction.id.desc())
            .limit(10)
        )
    ).scalars().all()

    recent_transfers = (
        await session.execute(
            select(Transfer)
            .where(Transfer.user_id == user.id)
            .order_by(Transfer.date.desc(), Transfer.id.desc())
            .limit(5)
        )
    ).scalars().all()

    runway_days = None
    if liquidity["equivalent_in_default_currency"] and current_month_flow["avg_daily_expense_default"]:
        liq_d = Decimal(liquidity["equivalent_in_default_currency"])
        burn_d = Decimal(current_month_flow["avg_daily_expense_default"])
        if burn_d > 0:
            runway_days = int((liq_d / burn_d).to_integral_value())

    cbu_rates_summary = None
    if rates is not None:
        cbu_rates_summary = {
            "effective_date": rates.effective_date.isoformat(),
            "stale": rates.stale,
            "USD_UZS": _dec_str(money_round(rates.ratio("USD", "UZS"))) if "USD" in rates.rates else None,
            "EUR_UZS": _dec_str(money_round(rates.ratio("EUR", "UZS"))) if "EUR" in rates.rates else None,
            "RUB_UZS": _dec_str(money_round(rates.ratio("RUB", "UZS"))) if "RUB" in rates.rates else None,
        }

    return {
        "as_of_date": today.isoformat(),
        "timezone": user.timezone or "Asia/Tashkent",
        "user_language": user.language or "ru",
        "default_currency": user.default_currency,
        "month_progress": {
            "month": month_str,
            "day_of_month": today.day,
            "days_in_month": days_in_month,
            "days_remaining": days_in_month - today.day,
            "elapsed_pct": _dec_str(month_elapsed_pct),
        },
        "accounts": accounts,
        "total_liquid_balances": liquidity,
        "estimated_runway_days_at_current_burn": runway_days,
        "current_month_cashflow": current_month_flow,
        "previous_month_cashflow": previous_month_flow,
        "budgets_this_month": budgets,
        "active_recurring_rules": recurring_list,
        "upcoming_recurring_expenses_until_month_end": _convert_totals(
            upcoming_recurring_expense_ccy, user.default_currency, rates
        ),
        "recent_10_transactions": [
            {
                "id": tx.id,
                "date": tx.date.isoformat(),
                "type": tx.type,
                "amount": _dec_str(tx.amount),
                "currency": tx.currency,
                "category": tx.category or "Другое",
                "description": tx.description or "",
                "account": acc_name_by_id.get(tx.account_id, {}).get("name", ""),
            }
            for tx in recent_txs
        ],
        "recent_5_transfers": [
            {
                "date": tr.date.isoformat(),
                "from": acc_name_by_id.get(tr.source_id, {}).get("name", str(tr.source_id)),
                "to": acc_name_by_id.get(tr.destination_id, {}).get("name", str(tr.destination_id)),
                "source_amount": _dec_str(tr.source_amount),
                "destination_amount": _dec_str(tr.destination_amount),
                "description": tr.description,
            }
            for tr in recent_transfers
        ],
        "cbu_exchange_rates": cbu_rates_summary,
    }


# ─── Read-Only Tool Implementations ──────────────────────────────────────────


async def tool_get_financial_overview(
    session: AsyncSession,
    user: User,
    rate_service: ExchangeRateService | None,
    period_days: int = 30,
) -> dict[str, Any]:
    days = max(1, min(int(period_days or 30), 3650))
    today = local_today(user)
    start = today - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    rates = await _safe_rate_book(session, rate_service)
    accounts = await compute_live_accounts(session, user)
    current = await _cashflow_summary(session, user, start, today, rates)
    previous = await _cashflow_summary(session, user, prev_start, prev_end, rates)
    budgets = await budget_status(session, user, month=today.strftime("%Y-%m"), create_alerts=False)

    return {
        "period_days": days,
        "accounts": accounts,
        "selected_period": current,
        "previous_equal_period": previous,
        "budgets_current_month": budgets,
    }


async def tool_query_transactions(
    session: AsyncSession,
    user: User,
    start_date: str | None = None,
    end_date: str | None = None,
    tx_type: str | None = None,
    category: str | None = None,
    account_name: str | None = None,
    search: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    sort_by: str = "date_desc",
    limit: int = 30,
) -> dict[str, Any]:
    filters = [Transaction.user_id == user.id]
    s_date = _parse_date(start_date)
    e_date = _parse_date(end_date)
    if s_date:
        filters.append(Transaction.date >= s_date)
    if e_date:
        filters.append(Transaction.date <= e_date)
    if tx_type in ("income", "expense"):
        filters.append(Transaction.type == tx_type)
    if category:
        filters.append(Transaction.category.ilike(f"%{category.strip()}%"))
    if search:
        term = search.strip()
        filters.append(
            Transaction.description.ilike(f"%{term}%") | Transaction.category.ilike(f"%{term}%")
        )
    if min_amount is not None:
        filters.append(Transaction.amount >= Decimal(str(min_amount)))
    if max_amount is not None:
        filters.append(Transaction.amount <= Decimal(str(max_amount)))

    accounts = (
        await session.execute(select(Account).where(Account.user_id == user.id))
    ).scalars().all()
    acc_name_by_id = {a.id: a.name for a in accounts}
    if account_name:
        needle = account_name.strip().lower()
        matching_ids = [a.id for a in accounts if needle in a.name.lower()]
        if not matching_ids:
            return {"total_matching_count": 0, "totals_by_currency": {}, "transactions": []}
        filters.append(Transaction.account_id.in_(matching_ids))

    # Exact aggregate across ALL matching rows
    agg_rows = (
        await session.execute(
            select(Transaction.type, Transaction.currency, func.count(), func.sum(Transaction.amount))
            .where(*filters)
            .group_by(Transaction.type, Transaction.currency)
        )
    ).all()
    total_count = sum(cnt for _, _, cnt, _ in agg_rows)
    totals_by_type_ccy: dict[str, dict[str, str]] = defaultdict(dict)
    for kind, ccy, _, amt in agg_rows:
        totals_by_type_ccy[kind][ccy] = _dec_str(amt or 0)

    order_clause = (
        (Transaction.amount.desc(), Transaction.date.desc())
        if sort_by == "amount_desc"
        else (Transaction.date.desc(), Transaction.id.desc())
    )
    safe_limit = max(1, min(int(limit or 30), 50))
    rows = (
        await session.execute(
            select(Transaction).where(*filters).order_by(*order_clause).limit(safe_limit)
        )
    ).scalars().all()

    return {
        "total_matching_count": total_count,
        "shown_count": len(rows),
        "totals_by_type_and_currency": dict(totals_by_type_ccy),
        "transactions": [
            {
                "id": tx.id,
                "date": tx.date.isoformat(),
                "type": tx.type,
                "amount": _dec_str(tx.amount),
                "currency": tx.currency,
                "category": tx.category or "Другое",
                "description": tx.description or "",
                "account": acc_name_by_id.get(tx.account_id, ""),
            }
            for tx in rows
        ],
    }


async def tool_analyze_spending_habits(
    session: AsyncSession,
    user: User,
    start_date: str | None = None,
    end_date: str | None = None,
    group_by: str = "category",
    include_reconcile: bool = False,
) -> dict[str, Any]:
    today = local_today(user)
    e_date = _parse_date(end_date, today) or today
    s_date = _parse_date(start_date, e_date - timedelta(days=89)) or (e_date - timedelta(days=89))

    filters = [
        Transaction.user_id == user.id,
        Transaction.type == "expense",
        Transaction.date >= s_date,
        Transaction.date <= e_date,
    ]
    if not include_reconcile:
        filters.append(func.coalesce(Transaction.category, "") != RECONCILE_CATEGORY)

    rows = (
        await session.execute(
            select(Transaction.date, Transaction.category, Transaction.description, Transaction.currency, Transaction.amount)
            .where(*filters)
        )
    ).all()

    buckets_sum: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    buckets_cnt: dict[tuple[str, str], int] = defaultdict(int)
    total_ccy: dict[str, Decimal] = defaultdict(Decimal)

    for tx_date, cat, desc, ccy, amt in rows:
        total_ccy[ccy] += amt
        if group_by == "month":
            key = tx_date.strftime("%Y-%m")
        elif group_by == "weekday":
            key = WEEKDAY_NAMES_RU[tx_date.weekday()]
        elif group_by == "description":
            key = (desc or cat or "Без описания").strip()[:60]
        else:
            key = cat or "Другое"
        buckets_sum[(key, ccy)] += amt
        buckets_cnt[(key, ccy)] += 1

    sorted_items = sorted(
        buckets_sum.items(),
        key=lambda kv: (kv[1], buckets_cnt[kv[0]]),
        reverse=True,
    )[:20]

    breakdown = []
    for (bucket_name, ccy), amt in sorted_items:
        cnt = buckets_cnt[(bucket_name, ccy)]
        ccy_total = total_ccy[ccy]
        share = money_round((amt / ccy_total) * Decimal(100)) if ccy_total > 0 else Decimal(0)
        breakdown.append(
            {
                "group": bucket_name,
                "currency": ccy,
                "total_amount": _dec_str(amt),
                "tx_count": cnt,
                "avg_ticket": _dec_str(money_round(amt / Decimal(cnt))),
                "share_of_currency_expense_pct": _dec_str(share),
            }
        )

    return {
        "start_date": s_date.isoformat(),
        "end_date": e_date.isoformat(),
        "group_by": group_by,
        "total_expense_by_currency": {k: _dec_str(v) for k, v in sorted(total_ccy.items())},
        "breakdown": breakdown,
    }


async def tool_simulate_financial_decision(
    session: AsyncSession,
    user: User,
    rate_service: ExchangeRateService | None,
    amount: float,
    currency: str | None = None,
    account_name: str | None = None,
    horizon_days: int = 30,
) -> dict[str, Any]:
    try:
        purchase_amt = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return {"error": "Invalid numeric amount."}
    if purchase_amt <= 0:
        return {"error": "Amount must be positive."}

    ccy = (currency or user.default_currency).strip().upper()
    horizon = max(1, min(int(horizon_days or 30), 365))
    today = local_today(user)
    horizon_end = today + timedelta(days=horizon)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_left_in_month = max(1, days_in_month - today.day + 1)

    rates = await _safe_rate_book(session, rate_service)
    accounts = await compute_live_accounts(session, user)

    target_accounts = [a for a in accounts if not a["archived"]]
    if account_name:
        needle = account_name.strip().lower()
        matched = [a for a in target_accounts if needle in a["name"].lower()]
        if matched:
            target_accounts = matched

    # Liquid balance in target currency + total equivalent in default currency
    same_ccy_balance = sum(
        (Decimal(a["balance"]) for a in target_accounts if a["currency"] == ccy),
        Decimal(0),
    )
    purchase_in_default = None
    if ccy == user.default_currency:
        purchase_in_default = purchase_amt
    elif rates is not None and ccy in rates.rates and user.default_currency in rates.rates:
        purchase_in_default = money_round(rates.convert(purchase_amt, ccy, user.default_currency))

    all_active_ccy: dict[str, Decimal] = defaultdict(Decimal)
    for a in accounts:
        if not a["archived"]:
            all_active_ccy[a["currency"]] += Decimal(a["balance"])
    total_liq = _convert_totals(all_active_ccy, user.default_currency, rates)

    # Upcoming recurring expenses within horizon_days
    rules = (
        await session.execute(
            select(RecurringRule).where(
                RecurringRule.user_id == user.id,
                RecurringRule.enabled.is_(True),
                RecurringRule.type == "expense",
            )
        )
    ).scalars().all()
    acc_by_id = {a["id"]: a for a in accounts if a["id"] is not None}
    upcoming_same_ccy = Decimal(0)
    upcoming_total_ccy: dict[str, Decimal] = defaultdict(Decimal)
    for rule in rules:
        rule_ccy = acc_by_id.get(rule.account_id, {}).get("currency", user.default_currency)
        if rule.next_date <= horizon_end:
            upcoming_total_ccy[rule_ccy] += rule.amount
            if rule_ccy == ccy:
                upcoming_same_ccy += rule.amount

    # Average daily burn in default currency over last 30 days
    month_flow = await _cashflow_summary(session, user, today - timedelta(days=29), today, rates)
    avg_daily_burn = (
        Decimal(month_flow["avg_daily_expense_default"])
        if month_flow["avg_daily_expense_default"]
        else Decimal(0)
    )

    after_same_ccy = same_ccy_balance - purchase_amt
    free_same_ccy_after_recurring = after_same_ccy - upcoming_same_ccy

    total_after_default = None
    free_default_after_recurring = None
    daily_allowance_until_month_end = None
    runway_days_after = None

    upcoming_conv = _convert_totals(upcoming_total_ccy, user.default_currency, rates)
    if total_liq["equivalent_in_default_currency"] is not None and purchase_in_default is not None:
        total_before = Decimal(total_liq["equivalent_in_default_currency"])
        total_after = total_before - purchase_in_default
        total_after_default = _dec_str(total_after)
        upcoming_def = Decimal(upcoming_conv["equivalent_in_default_currency"] or "0")
        free_def = total_after - upcoming_def
        free_default_after_recurring = _dec_str(free_def)
        daily_allowance_until_month_end = _dec_str(
            money_round(free_def / Decimal(days_left_in_month))
        )
        if avg_daily_burn > 0:
            runway_days_after = int((max(Decimal(0), total_after) / avg_daily_burn).to_integral_value())

    budgets = await budget_status(session, user, month=today.strftime("%Y-%m"), create_alerts=False)

    return {
        "purchase_amount": _dec_str(purchase_amt),
        "purchase_currency": ccy,
        "purchase_equivalent_default": _dec_str(purchase_in_default) if purchase_in_default is not None else None,
        "account_scope": account_name or f"Все активные счета в {ccy}",
        "horizon_days": horizon,
        "balance_in_target_currency_before": _dec_str(same_ccy_balance),
        "balance_in_target_currency_after": _dec_str(after_same_ccy),
        "upcoming_recurring_in_target_currency": _dec_str(upcoming_same_ccy),
        "free_in_target_currency_after_purchase_and_recurring": _dec_str(free_same_ccy_after_recurring),
        "total_liquid_default_after_purchase": total_after_default,
        "free_default_after_purchase_and_recurring": free_default_after_recurring,
        "sustainable_daily_allowance_until_month_end_default": daily_allowance_until_month_end,
        "avg_daily_burn_last_30d_default": _dec_str(avg_daily_burn),
        "estimated_runway_days_after_purchase": runway_days_after,
        "current_month_budgets": budgets,
    }


ADVISOR_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_financial_overview",
            "description": (
                "Получить точную сводку балансов счетов, доходов, расходов, нормы сбережений, "
                "дневного расхода и бюджетов за произвольное число дней (например 7, 30, 90, 365) "
                "в сравнении с предыдущим таким же периодом."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period_days": {
                        "type": "integer",
                        "description": "Количество дней назад от сегодняшней даты (по умолчанию 30).",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_transactions",
            "description": (
                "Поиск и фильтрация по всей истории транзакций пользователя. Возвращает точное "
                "количество и общую сумму всех совпадений по валютам, а также список операций."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Дата от (YYYY-MM-DD)"},
                    "end_date": {"type": "string", "description": "Дата до (YYYY-MM-DD)"},
                    "tx_type": {"type": "string", "enum": ["income", "expense"]},
                    "category": {"type": "string", "description": "Название категории или подстрока"},
                    "account_name": {"type": "string", "description": "Название счёта или карты"},
                    "search": {"type": "string", "description": "Поиск по описанию или категории"},
                    "min_amount": {"type": "number"},
                    "max_amount": {"type": "number"},
                    "sort_by": {"type": "string", "enum": ["date_desc", "amount_desc"]},
                    "limit": {"type": "integer", "description": "Сколько записей вернуть (1..50)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_spending_habits",
            "description": (
                "Анализ привычек расходов за период: группировка по категориям (category), "
                "частым статьям/местам трат (description), дням недели (weekday) или месяцам (month) "
                "с точным количеством транзакций, средним чеком и долей."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Дата от (YYYY-MM-DD)"},
                    "end_date": {"type": "string", "description": "Дата до (YYYY-MM-DD)"},
                    "group_by": {
                        "type": "string",
                        "enum": ["category", "description", "weekday", "month"],
                    },
                    "include_reconcile": {"type": "boolean"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_financial_decision",
            "description": (
                "Стресс-тест планируемой покупки или траты: считает остаток на счёте и в общей "
                "ликвидности, учитывает предстоящие регулярные списания за horizon_days, пересчитывает "
                "допустимый дневной расход до конца месяца и запас прочности (runway)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Сумма планируемой траты"},
                    "currency": {"type": "string", "description": "Валюта траты (UZS, USD, EUR и т.д.)"},
                    "account_name": {"type": "string", "description": "Счёт, с которого планируется списание"},
                    "horizon_days": {"type": "integer", "description": "Горизонт проверки обязательств в днях (по умолчанию 30)"},
                },
                "required": ["amount"],
            },
        },
    },
]


def build_advisor_system_prompt(
    user: User,
    snapshot: dict[str, Any],
    response_mode: str = "text",
    detail_level: str = "detailed",
) -> str:
    """Detailed domain methodology + live database state for the read-only AI financier."""
    lang_note = (
        "Предпочитаемый язык интерфейса пользователя: узбекский (O'zbek). Отвечай на языке вопроса пользователя (если вопрос на узбекском — на узбекском, если на русском — на русском)."
        if user.language == "uz"
        else "Предпочитаемый язык пользователя: русский. Если пользователь пишет на узбекском — отвечай на узбекском."
    )
    is_brief = detail_level == "brief"
    length_note = (
        "ОБЪЁМ ОТВЕТА (ПО ДЕЛУ): отвечай максимально коротко, тепло и по делу — строго около 350–500 символов "
        "(не длиннее 550 символов). Только главный ответ на вопрос, 2–3 реальные цифры и 1 понятный следующий шаг."
        if is_brief
        else "ОБЪЁМ ОТВЕТА (ПОДРОБНО): дай живой, тёплый и понятный разбор строго около 750–950 символов "
        "(не длиннее 1000 символов): прямой ответ, точные цифры по счетам/тратам, 2 простых варианта на выбор и 1 конкретный шаг."
    )
    if response_mode == "voice":
        tag_budget = "1–2" if is_brief else "2–3"
        delivery_note = (
            "ФОРМАТ ОЗВУЧКИ (VOICE + ElevenLabs v4): пользователь выбрал голосовой ответ. "
            "Говори как внимательный, добрый и при этом собранный живой наставник в личном разговоре — "
            "связной живой речью, без Markdown (`**`, `*`, `#`, `` ` ``), без эмодзи, таблиц и списков. "
            "Не используй математические символы вроде `≈`, `≤`, `≥` — пиши словами («около», «примерно», «не больше»). "
            "Валюты произноси естественно (например «4 миллиона сум», «200 долларов»). "
            f"Добавляй {tag_budget} уместных аудио-тега ElevenLabs v4 строго на английском в квадратных скобках прямо перед фразой: "
            "`[warmly]`, `[thoughtful]`, `[confident]`, `[curious]`, `[serious]`, `[delighted]`, `[sighs]`, `[chuckles]`, `[pause]`. "
            "Никогда не заключай в квадратные скобки числа или обычный текст. "
            f"{length_note}"
        )
    else:
        delivery_note = (
            "Форматируй суммы понятно (например `150 000 UZS`, `250 USD`). "
            "Пиши коротко, по-человечески, без воды, штампов и канцелярита. "
            f"{length_note}"
        )
    snapshot_json = json.dumps(snapshot, ensure_ascii=False)

    return f"""Ты — живой, заботливый и честный личный помощник по деньгам внутри приложения Mone.

=== 1. СТИЛЬ ОБЩЕНИЯ И ПРОСТОТА ===
- Проявляй лёгкую эмпатию и поддержку: если денег впритык или была лишняя трата — не читай нотации и не пугай, а спокойно поддержи («Вижу, бюджет сейчас плотный — давай разберёмся спокойно», «Отлично держишь темп!»).
- Пиши ТАК ПРОСТО И ПОНЯТНО, чтобы мысль с первого раза понял даже 10–15-летний подросток. Короткие предложения, обычные человеческие слова.
- ЗАПРЕЩЁН сложный финансовый жаргон и сухие штампы в ответе пользователю: НЕ используй слова «ликвидность», «Cash Flow», «Savings Rate», «Burn Rate», «Runway», «Budget Pacing», «правило Парето», «стресс-тест», «диагноз», «аудит», «оптимизация структуры расходов».
  Говори по-человечески:
  - вместо «ликвидность» -> «сколько сейчас есть на счетах и наличными»;
  - вместо «Cash Flow / Net» -> «сколько пришло и сколько ушло / что осталось»;
  - вместо «Burn Rate / Runway» -> «сколько тратишь в день и на сколько дней хватит»;
  - вместо «Budget Pacing» -> «с какой скоростью уходит бюджет».

=== 2. ОПОРА ТОЛЬКО НА РЕАЛЬНЫЕ АКТУАЛЬНЫЕ ДАННЫЕ ===
- У тебя под рукой живой срез базы прямо сейчас (ниже) и инструменты чтения (`query_transactions`, `analyze_spending_habits`, `simulate_financial_decision`, `get_financial_overview`).
- Для любых вопросов про прошлые траты, конкретные покупки, привычки, мелкие частые расходы (кофе, такси, еда) или планы на покупку ОБЯЗАТЕЛЬНО вызывай подходящие read-only инструменты — не угадывай по памяти.
- Различай операции в базе:
  - переводы между своими счетами (`Transfer`) — это просто перекладывание своих денег, НЕ доход и НЕ расход;
  - `Сверка` — техническая правка остатка, НЕ реальная покупка;
  - разные валюты нельзя складывать напрямую; перевод в основную валюту `{user.default_currency}` делай только по курсу ЦБ (`cbu_exchange_rates`).
- Всегда проверяй свежие остатки и `recent_10_transactions` в срезе/инструментах — если пользователь только что добавил или удалил трату, опирайся именно на новые цифры, а не на старые из прошлых сообщений.

=== 3. КАК СТРОИТЬ ОТВЕТ (КОРОТКО И ПО ДЕЛУ) ===
1. Сразу дай прямой и тёплый ответ по сути вопроса («Да, получится спокойно…», «Сейчас лучше чуть притормозить, потому что…»).
2. Подкрепи его 2–4 реальными цифрами из базы (сколько сейчас на нужном счёте, сколько ушло/осталось, сколько осталось дней).
3. Если есть выбор или проблема — предложи 2 простых и понятных варианта с понятными цифрами.
4. Заверши одним конкретным, посильным шагом (например: лимит на день или с какой карты лучше платить).

=== 4. ЖЁСТКИЕ ПРАВИЛА ===
- ТОЛЬКО ЧТЕНИЕ: ты не можешь сам добавлять, менять или удалять траты, счета и бюджеты. Если просят что-то записать или поправить — вежливо скажи, что здесь ты только подсказываешь, а записать можно, выйдя из режима («⬅️ Выйти из режима») или в самом приложении.
- НИЧЕГО НЕ ПРИДУМЫВАЙ: никогда не выдумывай суммы, даты, счета или будущие поступления. Если в базе чего-то нет — честно скажи, чего не хватает.
- {lang_note}
- {delivery_note}

=== ЖИВОЙ СРЕЗ БАЗЫ ДАННЫХ ПОЛЬЗОВАТЕЛЯ НА СЕЙЧАС ===
{snapshot_json}"""


class AIAdvisor:
    """Stateless-per-turn, DB-backed read-only financial advisor service."""

    def __init__(
        self,
        api_key: str,
        rate_service: ExchangeRateService | None = None,
        client: AsyncGroq | Groq | None = None,
        max_concurrency: int = 20,
    ):
        self._owns_client = client is None
        self.client = client or AsyncGroq(api_key=api_key, timeout=45.0, max_retries=1)
        self.rate_service = rate_service or ExchangeRateService()
        self.models = [PRIMARY_ADVISOR_MODEL, FALLBACK_ADVISOR_MODEL, TERTIARY_ADVISOR_MODEL]
        self._llm_semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))

    async def close(self) -> None:
        """Close the pooled AsyncGroq client if owned by this instance."""
        if self._owns_client and hasattr(self.client, "close"):
            res = self.client.close()
            if inspect.isawaitable(res):
                await res

    async def get_history(self, session: AsyncSession, user_id: int, limit: int = MAX_HISTORY_TURNS) -> list[dict[str, str]]:
        rows = (
            await session.execute(
                select(AdvisorMessage)
                .where(AdvisorMessage.user_id == user_id)
                .order_by(AdvisorMessage.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [{"role": row.role, "content": row.content} for row in reversed(rows)]

    async def clear_history(self, session: AsyncSession, user_id: int) -> int:
        res = await session.execute(
            delete(AdvisorMessage).where(AdvisorMessage.user_id == user_id)
        )
        await session.flush()
        return int(res.rowcount or 0)

    async def _execute_tool(
        self,
        session: AsyncSession,
        user: User,
        name: str,
        raw_args: str,
    ) -> str:
        try:
            args = json.loads(raw_args) if raw_args else {}
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            return json.dumps({"error": "Malformed tool arguments JSON"}, ensure_ascii=False)

        try:
            if name == "get_financial_overview":
                res = await tool_get_financial_overview(
                    session,
                    user,
                    self.rate_service,
                    period_days=args.get("period_days", 30),
                )
            elif name == "query_transactions":
                res = await tool_query_transactions(
                    session,
                    user,
                    start_date=args.get("start_date"),
                    end_date=args.get("end_date"),
                    tx_type=args.get("tx_type"),
                    category=args.get("category"),
                    account_name=args.get("account_name"),
                    search=args.get("search"),
                    min_amount=args.get("min_amount"),
                    max_amount=args.get("max_amount"),
                    sort_by=args.get("sort_by", "date_desc"),
                    limit=args.get("limit", 30),
                )
            elif name == "analyze_spending_habits":
                res = await tool_analyze_spending_habits(
                    session,
                    user,
                    start_date=args.get("start_date"),
                    end_date=args.get("end_date"),
                    group_by=args.get("group_by", "category"),
                    include_reconcile=bool(args.get("include_reconcile", False)),
                )
            elif name == "simulate_financial_decision":
                res = await tool_simulate_financial_decision(
                    session,
                    user,
                    self.rate_service,
                    amount=args.get("amount", 0),
                    currency=args.get("currency"),
                    account_name=args.get("account_name"),
                    horizon_days=args.get("horizon_days", 30),
                )
            else:
                res = {"error": f"Unknown read-only tool: {name}"}
        except Exception as exc:
            logger.error("Advisor tool %s failed (%s)", name, type(exc).__name__, exc_info=True)
            res = {"error": f"Tool execution failed: {type(exc).__name__}"}

        return json.dumps(res, ensure_ascii=False)

    async def _call_completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        use_tools: bool = True,
        max_tokens: int = 3500,
    ):
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.25,
            "max_tokens": max_tokens,
        }
        if use_tools:
            kwargs["tools"] = ADVISOR_TOOLS
            kwargs["tool_choice"] = "auto"

        create_fn = self.client.chat.completions.create
        if inspect.iscoroutinefunction(create_fn):
            return await create_fn(**kwargs)
        result = await asyncio.to_thread(create_fn, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _complete_with_fallback(
        self,
        messages: list[dict[str, Any]],
        use_tools: bool = True,
        max_tokens: int = 3500,
    ):
        last_exc: Exception | None = None
        last_response = None
        async with self._llm_semaphore:
            for model in self.models:
                try:
                    response = await self._call_completion(
                        model,
                        messages,
                        use_tools=use_tools,
                        max_tokens=max_tokens,
                    )
                    choice = response.choices[0].message
                    has_content = bool(strip_thinking(choice.content or ""))
                    has_tools = bool(getattr(choice, "tool_calls", None))
                    if has_content or has_tools:
                        return response
                    last_response = response
                    logger.warning("Advisor model %s returned empty completion, trying fallback", model)
                except Exception as exc:
                    last_exc = exc
                    logger.warning("Advisor model %s failed (%s), trying fallback if available", model, type(exc).__name__)
        if last_response is not None:
            return last_response
        assert last_exc is not None
        raise last_exc

    async def ask(
        self,
        session: AsyncSession,
        user: User,
        question: str,
        save_history: bool = True,
        response_mode: str = "text",
        detail_level: str = "detailed",
    ) -> str:
        """Answer a financial consultation question using live DB data + read-only tools."""
        mode = "voice" if response_mode == "voice" else "text"
        detail = "brief" if detail_level == "brief" else "detailed"
        max_tokens = 1600 if detail == "brief" else (2400 if mode == "voice" else 3500)
        snapshot = await build_live_financial_snapshot(session, user, self.rate_service)
        system_prompt = build_advisor_system_prompt(
            user,
            snapshot,
            response_mode=mode,
            detail_level=detail,
        )
        history = await self.get_history(session, user.id, limit=MAX_HISTORY_TURNS)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": question},
        ]

        answer_text = ""
        for round_idx in range(MAX_TOOL_ROUNDS):
            use_tools = round_idx < MAX_TOOL_ROUNDS - 1
            response = await self._complete_with_fallback(
                messages,
                use_tools=use_tools,
                max_tokens=max_tokens,
            )
            choice = response.choices[0].message
            tool_calls = getattr(choice, "tool_calls", None) or []

            if tool_calls and use_tools:
                messages.append(
                    {
                        "role": "assistant",
                        "content": choice.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments or "{}",
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )
                for tc in tool_calls:
                    tool_output = await self._execute_tool(
                        session,
                        user,
                        tc.function.name,
                        tc.function.arguments or "{}",
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_output,
                        }
                    )
                continue

            answer_text = strip_thinking(choice.content or "")
            if answer_text:
                break

        if not answer_text:
            answer_text = (
                "Kechirasiz, hozir javob tayyorlab bo‘lmadi. Savolni biroz boshqacha yozib ko‘ring."
                if user.language == "uz"
                else "Не удалось сформировать разбор. Попробуй переформулировать вопрос."
            )

        if save_history:
            clean_history_text = strip_tts_tags(answer_text) if mode == "voice" else answer_text
            session.add(AdvisorMessage(user_id=user.id, role="user", content=question))
            session.add(AdvisorMessage(user_id=user.id, role="assistant", content=clean_history_text or answer_text))
            await session.flush()

        return answer_text
