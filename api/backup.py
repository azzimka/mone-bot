"""Versioned, owner-scoped additive recovery. Existing ledger rows are never deleted."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from api.main import get_user, get_session
from api.schemas import TransactionInput, CategoryInput, PreferencesInput
from api.finance_schemas import Input, AccountInput, TransferInput, BudgetInput, RecurringInput
from bot.models import Account, Transfer, Transaction, Category, Budget, RecurringRule, RestoreLog
from bot.services.finance import ensure_accounts
from bot.services.web_import import fingerprint

class AccountArchive(AccountInput):
    id: int = Field(gt=0)
class EntryArchive(TransactionInput):
    currency: str = Field(pattern=r'^[A-Z]{3}$')
class CategoryArchive(CategoryInput):
    display_name: str | None = Field(default=None,max_length=100)
    is_archived: bool = False
class TransferArchive(TransferInput):
    pass
class RuleArchive(RecurringInput):
    enabled: bool = True
    anchor_day: int = Field(ge=1,le=31)
class BackupDocument(Input):
    format: Literal['mone-backup']
    version: Literal[1]
    owner: str = Field(min_length=1,max_length=30)
    created_at: str = Field(max_length=40)
    preferences: PreferencesInput | None = None
    accounts: list[AccountArchive] = Field(max_length=200)
    transactions: list[EntryArchive] = Field(max_length=20000)
    categories: list[CategoryArchive] = Field(default_factory=list,max_length=1000)
    transfers: list[TransferArchive] = Field(default_factory=list,max_length=20000)
    budgets: list[BudgetInput] = Field(default_factory=list,max_length=1000)
    recurring: list[RuleArchive] = Field(default_factory=list,max_length=1000)

router=APIRouter(prefix='/api')

@router.get('/backup')
async def export_backup(user=Depends(get_user),session=Depends(get_session)):
    await ensure_accounts(session,user)
    async def records(model):return (await session.execute(select(model).where(model.user_id==user.id))).scalars().all()
    accounts=await records(Account);entries=await records(Transaction);categories=await records(Category);transfers=await records(Transfer);budgets=await records(Budget);rules=await records(RecurringRule)
    if len(entries)>20000 or len(transfers)>20000:raise HTTPException(413,'To‘liq nusxa uchun administrator eksportidan foydalaning.')
    def fields(row,names):return {name:getattr(row,name) for name in names.split()}
    data={'format':'mone-backup','version':1,'owner':str(user.telegram_id),'created_at':datetime.now(timezone.utc).isoformat(),
          'preferences':{'currency':user.default_currency,'timezone':user.timezone,'week_start':user.week_start,'quick_categories':json.loads(user.quick_categories or '[]'),'language':user.language},
          'accounts':[fields(row,'id name kind currency opening_balance') for row in accounts],
          'transactions':[fields(row,'type amount date category description account_id currency')|{'category':row.category or 'Другое','description':row.description or ''} for row in entries],
          'categories':[fields(row,'name display_name name_uz name_ru icon parent_name is_archived')|{'icon':row.icon if row.icon and row.icon.isascii() else None} for row in categories],
          'transfers':[fields(row,'source_id destination_id source_amount destination_amount date description request_key') for row in transfers],
          'budgets':[fields(row,'month category currency amount notify_telegram') for row in budgets],
          'recurring':[fields(row,'account_id type amount category description frequency next_date enabled anchor_day') for row in rules]}
    validated=BackupDocument.model_validate(data)
    await session.commit()
    return validated.model_dump(mode='json')

@router.post('/backup/preview')
async def preview_backup(body:BackupDocument,user=Depends(get_user)):
    if body.owner!=str(user.telegram_id):raise HTTPException(409,'Bu zaxira boshqa Telegram hisobiga tegishli.')
    return {'transactions':len(body.transactions),'accounts':len(body.accounts),'transfers':len(body.transfers),'categories':len(body.categories),'recurring':len(body.recurring),'budgets':len(body.budgets)}

@router.post('/backup/restore')
async def restore_backup(body:BackupDocument,user=Depends(get_user),session=Depends(get_session)):
    await preview_backup(body,user)
    encoded=json.dumps(body.model_dump(mode='json'),sort_keys=True).encode()
    file_hash=hashlib.sha256(encoded).hexdigest()
    accounts=await ensure_accounts(session,user)
    # An earlier restore is an audit record, not proof that its rows still exist.
    # Reconcile again so this same file can recover a subsequent accidental deletion.
    previously_restored=(await session.execute(select(RestoreLog.id).where(RestoreLog.user_id==user.id,RestoreLog.file_hash==file_hash))).scalar_one_or_none() is not None
    changed=False
    mapping={}
    if len({item.id for item in body.accounts})!=len(body.accounts):raise HTTPException(422,'Zaxiradagi hisoblar takrorlangan.')
    for record in body.accounts:
        account=next((item for item in accounts if item.name==record.name),None)
        if account and account.currency!=record.currency:raise HTTPException(409,'Hisob nomi mavjud, ammo valyutasi boshqa.')
        if account is None:
            account=Account(user_id=user.id,**record.model_dump(exclude={'id'}))
            session.add(account);await session.flush();accounts.append(account)
            changed=True
        mapping[record.id]=account.id
    def mapped(key):
        if key not in mapping:raise HTTPException(422,'Zaxirada hisobga bog‘lanish noto‘g‘ri.')
        return mapping[key]
    existing_categories=(await session.execute(select(Category).where(Category.user_id==user.id))).scalars().all()
    for record in body.categories:
        if not any(item.name==record.name for item in existing_categories):
            item=Category(user_id=user.id,is_default=False,**record.model_dump())
            session.add(item);existing_categories.append(item)
            changed=True
    await session.flush()
    from bot.services.categories import category_catalog
    catalog=await category_catalog(session,user.id)
    # A malformed backup must not introduce orphaned or cyclic category trees.
    by_name={item['name']:item for item in catalog}
    for item in catalog:
        if item['parent_name'] and (item['parent_name'] not in by_name or by_name[item['parent_name']]['parent_name']):raise HTTPException(422,'Zaxirada kategoriya tuzilishi noto‘g‘ri.')
    existing=(await session.execute(select(Transaction).where(Transaction.user_id==user.id))).scalars().all()
    counts=Counter(fingerprint({'date':row.date,'type':row.type,'amount':row.amount,'currency':row.currency,'category':row.category,'description':row.description,'account_id':row.account_id}) for row in existing)
    restored=skipped=0
    account_by_id={item.id:item for item in accounts}
    for row in body.transactions:
        data=row.model_dump();data['account_id']=mapped(row.account_id)
        if account_by_id[data['account_id']].currency!=row.currency:raise HTTPException(422,'Zaxiradagi hisob va yozuv valyutasi mos emas.')
        key=fingerprint(data)
        if counts[key]>0:counts[key]-=1;skipped+=1;continue
        session.add(Transaction(user_id=user.id,**data));restored+=1
        changed=True
    transfer_keys=set((await session.execute(select(Transfer.request_key).where(Transfer.user_id==user.id))).scalars())
    for row in body.transfers:
        if row.request_key in transfer_keys:continue
        source,destination=mapped(row.source_id),mapped(row.destination_id)
        if source==destination or row.destination_amount is None:raise HTTPException(422,'Zaxiradagi o‘tkazma noto‘g‘ri.')
        if account_by_id[source].currency==account_by_id[destination].currency and row.source_amount!=row.destination_amount:raise HTTPException(422,'Zaxiradagi o‘tkazma summalari mos emas.')
        session.add(Transfer(user_id=user.id,**{**row.model_dump(),'source_id':source,'destination_id':destination}));transfer_keys.add(row.request_key)
        changed=True
    budget_keys=set((await session.execute(select(Budget.month,Budget.category,Budget.currency).where(Budget.user_id==user.id))).all())
    for row in body.budgets:
        key=(row.month,row.category,row.currency)
        if key not in budget_keys:
            session.add(Budget(user_id=user.id,**{**row.model_dump(),'notify_telegram':False}));budget_keys.add(key)
            changed=True
    rules=(await session.execute(select(RecurringRule).where(RecurringRule.user_id==user.id))).scalars().all()
    for row in body.recurring:
        account_id=mapped(row.account_id)
        if any((item.account_id,item.type,item.amount,item.category,item.frequency,item.description)==(account_id,row.type,row.amount,row.category,row.frequency,row.description) for item in rules):continue
        # Restored automations require explicit re-enabling by their owner.
        item=RecurringRule(user_id=user.id,**{**row.model_dump(),'account_id':account_id,'enabled':False})
        session.add(item);rules.append(item)
        changed=True
    if body.preferences:
        for key,value in body.preferences.model_dump(exclude_none=True).items():
            if key=='language' and user.language is None:continue
            if key=='quick_categories':
                available={item['name'] for item in catalog if not item['archived']}
                value=json.dumps([name for name in value if name in available])
            field='default_currency' if key=='currency' else key
            if getattr(user,field)!=value:changed=True
            setattr(user,field,value)
    if not previously_restored:session.add(RestoreLog(user_id=user.id,file_hash=file_hash))
    await session.commit()
    return {'restored':restored,'skipped':skipped,'already_restored':previously_restored and not changed}
