from bot.services.i18n import tr, button_variants
"""CSV imports share a transaction with their ledger rows."""

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.csv_import import CsvImport
from bot.models.transaction import Transaction
from bot.models.user import User
from bot.services.csv_import import CsvImportError, CsvPreview


async def stage_import(session: AsyncSession, user_id: int, filename: str,
                       data: bytes, preview: CsvPreview) -> CsvImport:
    digest = hashlib.sha256(data).hexdigest()
    query = select(CsvImport).where(CsvImport.user_id == user_id, CsvImport.file_hash == digest).with_for_update()
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        try:
            async with session.begin_nested():
                item = CsvImport(id=str(uuid.uuid4()), user_id=user_id, file_hash=digest,
                                 filename=filename[:255], source_text=preview.source_text,
                                 rows_json="[]", expires_at=datetime.now(timezone.utc))
                session.add(item)
                await session.flush()
        except IntegrityError:
            # A concurrent upload of the same file won the unique constraint.
            item = (await session.execute(query)).scalar_one()
    if item.status == "complete":
        raise CsvImportError(tr('Этот CSV уже импортирован. Повторная загрузка не создаёт копии операций.'))
    item.rows_json = json.dumps([tx.to_dict() for tx in preview.transactions], ensure_ascii=False)
    item.status = "pending"
    item.expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await session.flush()
    return item


async def finish_import(session: AsyncSession, import_id: str, telegram_id: int,
                        *, cancel: bool = False) -> int:
    # Serialize imports and ledger duplicate checks across this owner, not just this file.
    await session.execute(select(User.id).where(User.telegram_id == telegram_id).with_for_update())
    # PostgreSQL serializes confirm/cancel requests for the same import.
    query = (select(CsvImport).join(User, CsvImport.user_id == User.id)
             .where(CsvImport.id == import_id, User.telegram_id == telegram_id)
             .with_for_update(of=CsvImport))
    item = (await session.execute(query)).scalar_one_or_none()
    if item is None:
        raise CsvImportError(tr('Импорт не найден или принадлежит другому пользователю.'))
    if item.status != "pending":
        raise CsvImportError(tr('Этот импорт уже завершён или отменён.'))
    expires = item.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise CsvImportError(tr('Подтверждение устарело. Отправьте CSV заново.'))
    if cancel:
        item.status = "cancelled"
        await session.flush()
        return 0
    rows = json.loads(item.rows_json)
    from bot.services.finance import owned_account, check_category, budget_status
    from bot.services.web_import import fingerprint
    user = await session.get(User, item.user_id)
    options = json.loads(item.options_json or '{}')
    seen = set()
    if options.get('skip_duplicates'):
        existing = (await session.execute(select(Transaction).where(Transaction.user_id == user.id))).scalars().all()
        seen = {fingerprint({'date':tx.date,'type':tx.type,'amount':tx.amount,'currency':tx.currency,'category':tx.category,'description':tx.description,'account_id':tx.account_id}) for tx in existing}
    count = 0
    for row in rows:
        try:
            account = await owned_account(session, user, row.get('account_id'), row['currency'])
            await check_category(session, user.id, row['category'])
        except ValueError as error:
            raise CsvImportError(str(error))
        row['account_id'] = account.id
        key = fingerprint(row)
        if options.get('skip_duplicates') and key in seen: continue
        seen.add(key)
        session.add(Transaction(user_id=item.user_id, account_id=account.id, type=row['type'], amount=Decimal(row['amount']),
                                currency=row['currency'], category=row['category'], description=row['description'], date=date.fromisoformat(row['date'])))
        count += 1
    item.status = 'complete'
    await session.flush()
    await budget_status(session, user)
    return count
