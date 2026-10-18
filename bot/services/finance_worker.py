"""Single-process worker; database locks also protect overlapping deployments."""
import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from bot.models import User, Budget, BudgetAlert, RecurringRule
from bot.services.finance import ensure_accounts, recurring_due, budget_status

logger=logging.getLogger(__name__)

async def finance_tick(pool,bot):
    async with pool() as session:
        owners=set((await session.execute(select(Budget.user_id))).scalars())|set((await session.execute(select(RecurringRule.user_id))).scalars())
    for owner in owners:
        try:
            async with pool.begin() as session:
                user=await session.get(User,owner)
                await ensure_accounts(session,user)
                await recurring_due(session,user)
                await budget_status(session,user)
        except Exception as error:
            logger.warning('Financial automation failed (%s)',type(error).__name__)
    async with pool.begin() as session:
        pending=(await session.execute(select(BudgetAlert,Budget,User).join(Budget,BudgetAlert.budget_id==Budget.id).join(User,Budget.user_id==User.id).where(BudgetAlert.delivered_at.is_(None),BudgetAlert.attempts<3,Budget.notify_telegram.is_(True)).with_for_update(of=BudgetAlert,skip_locked=True).limit(100))).all()
        for alert,budget,user in pending:
            # Explicit per-budget opt-in is required; no historical users are opted in.
            alert.attempts+=1
            from bot.services.categories import category_catalog
            from bot.services.i18n import CATEGORY_LABELS
            category=next((item for item in await category_catalog(session,user.id) if item['name']==budget.category),None)
            label=((category.get('name_ru') if user.language=='ru' else category.get('name_uz')) or category['display_name'] or (CATEGORY_LABELS.get(budget.category,budget.category) if user.language!='ru' else budget.category)) if category else budget.category
            label=label or ('Общий бюджет' if user.language=='ru' else 'Umumiy byudjet')
            message=(f'⚠️ Бюджет: {label}\n{budget.month} · достигнут порог {alert.level}%\nЛимит: {budget.amount} {budget.currency}' if user.language=='ru' else f'⚠️ Byudjet: {label}\n{budget.month} · {alert.level}% chegaraga yetdi\nLimit: {budget.amount} {budget.currency}')
            try:
                await bot.send_message(user.telegram_id,message)
                alert.delivered_at=datetime.now(timezone.utc)
            except Exception as error:
                logger.warning('Budget delivery failed (%s)',type(error).__name__)

async def finance_worker(pool,bot):
    while True:
        try:await finance_tick(pool,bot)
        except Exception as error:logger.warning('Financial worker failed (%s)',type(error).__name__)
        await asyncio.sleep(60)
