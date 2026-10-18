"""Confirm only the owner's pending entries and keep every currency separate."""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories import TransactionRepository
from bot.handlers.commands import fmt
from bot.models import User
from bot.services.csv_import import CsvImportError, parse_amount
from bot.services.finance import balance_totals, local_today, owned_account
from bot.services.i18n import category_label, current_language, tr

logger = logging.getLogger(__name__)
router = Router()

# UUID -> owner database ID, parsed entry and source text. A click can be handled
# only once at a time, including while an awaited database write is running.
pending_transactions: dict[str, dict] = {}
processing_transactions: set[str] = set()


def _localized(uz: str, ru: str) -> str:
    return uz if current_language.get() == "uz" else ru


async def _pending_owner(callback: CallbackQuery, session: AsyncSession, pending: dict) -> User | None:
    owner = await session.get(User, pending["user_id"])
    if owner is None or owner.telegram_id != callback.from_user.id:
        await callback.answer(_localized("Bu yozuv sizga tegishli emas.", "Эта запись принадлежит другому пользователю."), show_alert=True)
        return None
    return owner


@router.callback_query(F.data.startswith("confirm:"))
async def on_confirm_transaction(callback: CallbackQuery, session: AsyncSession):
    tx_id = callback.data.split(":", 1)[1]
    pending = pending_transactions.get(tx_id)
    if pending is None:
        await callback.answer(tr("❌ Данная операция уже обработана или устарела."), show_alert=True)
        return
    user = await _pending_owner(callback, session, pending)
    if user is None:
        return
    if tx_id in processing_transactions:
        await callback.answer(_localized("Yozuv saqlanmoqda…", "Запись сохраняется…"))
        return
    processing_transactions.add(tx_id)
    committed = False
    try:
        tx = pending["transaction"]
        currency = tx.get("currency") or user.default_currency
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("Invalid currency")
        currency = currency.upper()
        amount = parse_amount(str(tx["amount"]))
        kind = tx["type"]
        if kind not in {"income", "expense", "reconcile"} or amount < 0 or (kind != "reconcile" and amount == 0):
            raise ValueError("Invalid transaction")
        account = await owned_account(session, user, tx.get("account_id"), currency)

        if kind == "reconcile":
            totals = await balance_totals(session, user, currency, account.id)
            before = totals["balance"]
            difference = amount - before
            if difference:
                await TransactionRepository.create(
                    session=session, user_id=user.id, account_id=account.id,
                    type="income" if difference > 0 else "expense", amount=abs(difference),
                    currency=currency, category="Сверка",
                    description=f"Сверка ({difference:+f} {currency})",
                    voice_text=pending.get("voice_text", ""), date=local_today(user),
                )
            success = _localized(
                f"⚖️ Balans tenglashtirildi\n💳 {account.name}\nOldin: {fmt(before, currency)}\nHozir: {fmt(amount, currency)}",
                f"⚖️ Баланс сверен\n💳 {account.name}\nБыло: {fmt(before, currency)}\nСейчас: {fmt(amount, currency)}",
            )
        else:
            await TransactionRepository.create(
                session=session, user_id=user.id, account_id=account.id,
                type=kind, amount=amount, currency=currency,
                category=tx.get("category", "Другое"), description=tx.get("description", ""),
                voice_text=pending.get("voice_text", ""), date=local_today(user),
            )
            success = f"✅ {tr('Доход') if kind == 'income' else tr('Расход')}: {fmt(amount, currency)}\n📂 {category_label(tx.get('category', 'Другое'))}"
            if kind == "expense":
                totals = await balance_totals(session, user, currency)
                success += _localized(
                    f"\n\n💵 Qoldiq: {fmt(totals['balance'], currency)}",
                    f"\n\n💵 Остаток: {fmt(totals['balance'], currency)}",
                )
        # A successful Telegram message must mean the ledger is durable. Remove
        # the pending entry before network delivery so a failed edit cannot make
        # a later click save the already committed transaction a second time.
        await session.commit()
        committed = True
        pending_transactions.pop(tx_id, None)
        await callback.message.edit_text(success)
        await callback.answer(tr("✅ Успешно сохранено!"))
    except (ValueError, CsvImportError):
        if committed:
            raise
        await session.rollback()
        await callback.answer(_localized("Yozuv saqlanmadi. Summa, valyuta va kategoriyani tekshiring.", "Запись не сохранена. Проверьте сумму, валюту и категорию."), show_alert=True)
    except Exception as exc:
        if committed:
            raise
        await session.rollback()
        logger.error("Transaction confirmation failed (%s)", type(exc).__name__)
        await callback.answer(_localized("Saqlanmadi. Tasdiqlash tugmasini qayta bosing.", "Не сохранено. Нажмите подтверждение ещё раз."), show_alert=True)
    finally:
        processing_transactions.discard(tx_id)


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel_transaction(callback: CallbackQuery, session: AsyncSession):
    tx_id = callback.data.split(":", 1)[1]
    pending = pending_transactions.get(tx_id)
    if pending is None:
        await callback.answer(tr("❌ Данная операция уже обработана или устарела."), show_alert=True)
        return
    if await _pending_owner(callback, session, pending) is None:
        return
    if tx_id in processing_transactions:
        await callback.answer(_localized("Yozuv saqlanmoqda…", "Запись сохраняется…"))
        return
    pending_transactions.pop(tx_id, None)
    await callback.message.edit_text(tr("❌ Операция отменена."))
    await callback.answer(tr("Отменено"))
