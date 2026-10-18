"""Decimal accounting and idempotent, opt-in scheduled ledger entries."""
import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select, update, func
from bot.models import Account, Transfer, Transaction, User, Budget, BudgetAlert, RecurringRule, RecurringOccurrence
from bot.services.categories import category_catalog


def local_today(user: User) -> date:
    return datetime.now(ZoneInfo(user.timezone or "Asia/Tashkent")).date()


async def ensure_accounts(session, user: User) -> list[Account]:
    # Serialize first-account creation and legacy backfill per account owner.
    await session.execute(select(User.id).where(User.id == user.id).with_for_update())
    accounts = list((await session.execute(select(Account).where(Account.user_id == user.id).order_by(Account.id))).scalars())
    currencies = set((await session.execute(select(Transaction.currency).where(Transaction.user_id == user.id).distinct())).scalars()) | {user.default_currency}
    for currency in sorted(currencies):
        target = next((item for item in accounts if item.currency == currency and not item.archived), None)
        if target is None:
            name = f"Naqd {currency}"
            while any(item.name == name for item in accounts): name += " +"
            target = Account(user_id=user.id, name=name, kind="cash", currency=currency)
            session.add(target)
            await session.flush()
            accounts.append(target)
        await session.execute(update(Transaction).where(Transaction.user_id == user.id, Transaction.currency == currency, Transaction.account_id.is_(None)).values(account_id=target.id))
    return accounts


async def owned_account(session, user: User, account_id: int | None, currency: str | None = None) -> Account:
    accounts = await ensure_accounts(session, user)
    if account_id is None:
        item = next((item for item in accounts if item.currency == (currency or user.default_currency) and not item.archived), None)
        if item is None:
            item = Account(user_id=user.id, name=f"Naqd {currency}", kind="cash", currency=currency)
            session.add(item)
            await session.flush()
    else:
        item = next((item for item in accounts if item.id == account_id and not item.archived), None)
    if item is None: raise ValueError("Hisob topilmadi.")
    if currency and item.currency != currency: raise ValueError("Hisob va operatsiya valyutasi bir xil bo‘lishi kerak.")
    return item


async def check_category(session, user_id: int, category: str, existing: str | None = None):
    item = next((item for item in await category_catalog(session, user_id) if item["name"] == category), None)
    if item and item["archived"] and existing != category:
        raise ValueError("Arxivlangan kategoriyaga yangi yozuv qo‘shib bo‘lmaydi.")


async def balance_adjustment(session, user_id: int, currency: str, account_id: int | None = None) -> Decimal:
    accounts = (await session.execute(select(Account).where(Account.user_id == user_id, Account.currency == currency))).scalars().all()
    ids = [item.id for item in accounts if account_id is None or item.id == account_id]
    total = sum((item.opening_balance for item in accounts if item.id in ids), Decimal(0))
    if ids:
        transfers = (await session.execute(select(Transfer).where(Transfer.user_id == user_id))).scalars().all()
        total += sum((item.destination_amount for item in transfers if item.destination_id in ids), Decimal(0))
        total -= sum((item.source_amount for item in transfers if item.source_id in ids), Decimal(0))
    return total


async def account_balances(session, user: User) -> list[dict]:
    accounts = await ensure_accounts(session, user)
    totals = (await session.execute(select(Transaction.account_id, Transaction.type, func.sum(Transaction.amount)).where(Transaction.user_id == user.id).group_by(Transaction.account_id, Transaction.type))).all()
    result = []
    for account in accounts:
        value = sum((amount if kind == "income" else -amount if kind == "expense" else Decimal(0) for key, kind, amount in totals if key == account.id), Decimal(0))
        value += await balance_adjustment(session, user.id, account.currency, account.id)
        result.append({"id": account.id, "name": account.name, "kind": account.kind, "currency": account.currency, "balance": str(value), "opening_balance": str(account.opening_balance)})
    return result


def next_occurrence(day: date, frequency: str, anchor: int) -> date:
    if frequency == "daily": return day + timedelta(days=1)
    if frequency == "weekly": return day + timedelta(days=7)
    month = day.month % 12 + 1
    year = day.year + (day.month == 12)
    return date(year, month, min(anchor, calendar.monthrange(year, month)[1]))


async def recurring_due(session, user: User, today: date | None = None) -> int:
    today = today or local_today(user)
    rules = (await session.execute(select(RecurringRule).where(RecurringRule.user_id == user.id, RecurringRule.enabled.is_(True), RecurringRule.next_date <= today).with_for_update(skip_locked=True))).scalars().all()
    count = 0
    for rule in rules:
        for _ in range(31):
            if rule.next_date > today: break
            due = rule.next_date
            found = (await session.execute(select(RecurringOccurrence.id).where(RecurringOccurrence.rule_id == rule.id, RecurringOccurrence.date == due))).scalar_one_or_none()
            if found is None:
                try: await check_category(session, user.id, rule.category)
                except ValueError:
                    rule.enabled = False
                    break
                account = await owned_account(session, user, rule.account_id)
                item = Transaction(user_id=user.id, account_id=account.id, type=rule.type, amount=rule.amount, currency=account.currency, category=rule.category, description=rule.description, date=due)
                session.add(item)
                await session.flush()
                session.add(RecurringOccurrence(rule_id=rule.id, date=due, transaction_id=item.id))
                count += 1
            rule.next_date = next_occurrence(due, rule.frequency, rule.anchor_day)
    await session.flush()
    return count


async def budget_status(session, user: User, month: str | None = None, create_alerts: bool = True) -> list[dict]:
    budgets = (await session.execute(select(Budget).where(Budget.user_id == user.id).order_by(Budget.month.desc(), Budget.id))).scalars().all()
    catalog = await category_catalog(session, user.id)
    result = []
    for budget in budgets:
        if month and budget.month != month: continue
        year, number = map(int, budget.month.split("-"))
        start, end = date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])
        query = select(func.coalesce(func.sum(Transaction.amount), 0)).where(Transaction.user_id == user.id, Transaction.currency == budget.currency, Transaction.type == "expense", Transaction.date >= start, Transaction.date <= end)
        if budget.category:
            keys = [budget.category] + [item["name"] for item in catalog if item["parent_name"] == budget.category]
            query = query.where(Transaction.category.in_(keys))
        spent = (await session.execute(query)).scalar_one()
        percent = spent / budget.amount * 100
        if create_alerts:
            for level in (80, 100):
                if percent >= level:
                    found = (await session.execute(select(BudgetAlert.id).where(BudgetAlert.budget_id == budget.id, BudgetAlert.level == level))).scalar_one_or_none()
                    if found is None: session.add(BudgetAlert(budget_id=budget.id, level=level))
        result.append({"id": budget.id, "month": budget.month, "category": budget.category, "currency": budget.currency, "amount": str(budget.amount), "spent": str(spent), "remaining": str(budget.amount-spent), "percent": str(percent), "notify_telegram": budget.notify_telegram})
    await session.flush()
    return result
