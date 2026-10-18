"""Authenticated account, planning and import endpoints."""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from api.main import get_user, get_session
from api.finance_schemas import AccountInput, TransferInput, BudgetInput, RecurringInput, EnabledInput, ArchiveInput, CsvInspectInput, CsvPreviewInput
from bot.models import Account, Transfer, Budget, RecurringRule, Category, User
from bot.database.csv_imports import finish_import
from bot.services.categories import category_catalog, normalized
from bot.services.finance import ensure_accounts, owned_account, account_balances, check_category, budget_status, recurring_due, local_today
from bot.services.web_import import inspect_csv, preview_csv
from bot.services.csv_import import CsvImportError

router=APIRouter(prefix='/api')

@router.get('/accounts')
async def accounts(user=Depends(get_user),session=Depends(get_session)):
    result=await account_balances(session,user)
    await session.commit()
    return result

@router.post('/accounts',status_code=201)
async def add_account(body:AccountInput,user=Depends(get_user),session=Depends(get_session)):
    current=await ensure_accounts(session,user)
    if any(normalized(item.name)==normalized(body.name) for item in current):raise HTTPException(409,'Bunday hisob mavjud.')
    item=Account(user_id=user.id,**body.model_dump())
    session.add(item)
    await session.commit()
    return {'id':item.id}

@router.get('/transfers')
async def transfers(user=Depends(get_user),session=Depends(get_session)):
    records=(await session.execute(select(Transfer).where(Transfer.user_id==user.id).order_by(Transfer.date.desc(),Transfer.id.desc()).limit(100))).scalars().all()
    return [{'id':row.id,'source_id':row.source_id,'destination_id':row.destination_id,'source_amount':str(row.source_amount),'destination_amount':str(row.destination_amount),'date':row.date,'description':row.description} for row in records]

@router.post('/transfers',status_code=201)
async def add_transfer(body:TransferInput,user=Depends(get_user),session=Depends(get_session)):
    try:
        source=await owned_account(session,user,body.source_id)
        destination=await owned_account(session,user,body.destination_id)
    except ValueError as error:raise HTTPException(404,str(error))
    if source.id==destination.id:raise HTTPException(422,'Ikki xil hisobni tanlang.')
    amount=body.destination_amount
    if source.currency==destination.currency:
        if amount is not None and amount!=body.source_amount:raise HTTPException(422,'Bir xil valyutada ikkala summa teng bo‘lishi kerak.')
        amount=body.source_amount
    elif amount is None:raise HTTPException(422,'Tushadigan summani o‘z valyutasida kiriting.')
    existing=(await session.execute(select(Transfer).where(Transfer.user_id==user.id,Transfer.request_key==body.request_key))).scalar_one_or_none()
    if existing:
        if (existing.source_id,existing.destination_id,existing.source_amount,existing.destination_amount,existing.date,existing.description)!=(source.id,destination.id,body.source_amount,amount,body.date,body.description):raise HTTPException(409,'O‘tkazma so‘rovi allaqachon ishlatilgan.')
        return {'id':existing.id}
    item=Transfer(user_id=user.id,**{**body.model_dump(),'destination_amount':amount})
    session.add(item)
    await session.commit()
    return {'id':item.id}

@router.get('/budgets')
async def budgets(month:str|None=None,user=Depends(get_user),session=Depends(get_session)):
    await ensure_accounts(session,user)
    result=await budget_status(session,user,month)
    await session.commit()
    return result

@router.post('/budgets',status_code=201)
async def save_budget(body:BudgetInput,user=Depends(get_user),session=Depends(get_session)):
    await ensure_accounts(session,user)
    if body.category:
        if not any(item['name']==body.category for item in await category_catalog(session,user.id)):raise HTTPException(422,'Kategoriya topilmadi.')
        try:await check_category(session,user.id,body.category)
        except ValueError as error:raise HTTPException(409,str(error))
    existing=(await session.execute(select(Budget).where(Budget.user_id==user.id,Budget.month==body.month,Budget.category==body.category,Budget.currency==body.currency))).scalar_one_or_none()
    if existing:
        for key,value in body.model_dump().items():setattr(existing,key,value)
    else:session.add(Budget(user_id=user.id,**body.model_dump()))
    await session.flush()
    result=await budget_status(session,user,body.month)
    await session.commit()
    return result

@router.get('/recurring')
async def recurring(user=Depends(get_user),session=Depends(get_session)):
    await ensure_accounts(session,user)
    await recurring_due(session,user)
    await budget_status(session,user)
    records=(await session.execute(select(RecurringRule).where(RecurringRule.user_id==user.id).order_by(RecurringRule.id.desc()))).scalars().all()
    await session.commit()
    return [{'id':row.id,'account_id':row.account_id,'type':row.type,'amount':str(row.amount),'category':row.category,'description':row.description,'frequency':row.frequency,'next_date':row.next_date,'enabled':row.enabled} for row in records]

@router.post('/recurring',status_code=201)
async def add_recurring(body:RecurringInput,user=Depends(get_user),session=Depends(get_session)):
    try:
        await owned_account(session,user,body.account_id)
        await check_category(session,user.id,body.category)
    except ValueError as error:raise HTTPException(409,str(error))
    if not 0<=(body.next_date-local_today(user)).days<=3660:raise HTTPException(422,'Boshlanish sanasi bugun yoki kelajakda bo‘lishi kerak.')
    item=RecurringRule(user_id=user.id,anchor_day=body.next_date.day,**body.model_dump())
    session.add(item)
    await session.commit()
    return {'id':item.id}

@router.patch('/recurring/{rule_id}')
async def toggle_recurring(rule_id:int,body:EnabledInput,user=Depends(get_user),session=Depends(get_session)):
    item=(await session.execute(select(RecurringRule).where(RecurringRule.user_id==user.id,RecurringRule.id==rule_id).with_for_update())).scalar_one_or_none()
    if not item:raise HTTPException(404,'Takroriy yozuv topilmadi.')
    if body.enabled and not item.enabled:
        try:await check_category(session,user.id,item.category)
        except ValueError as error:raise HTTPException(409,str(error))
        if item.next_date<local_today(user):item.next_date=local_today(user)
    item.enabled=body.enabled
    await session.commit()
    return {'id':item.id,'enabled':item.enabled}

@router.post('/category-settings/archive')
async def archive_category(body:ArchiveInput,user=Depends(get_user),session=Depends(get_session)):
    catalog=await category_catalog(session,user.id)
    item=next((item for item in catalog if item['name']==body.key),None)
    if item is None:raise HTTPException(404,'Kategoriya topilmadi.')
    if not body.archived and item['parent_name'] and any(row['name']==item['parent_name'] and row['archived'] for row in catalog):raise HTTPException(409,'Avval asosiy kategoriyani tiklang.')
    record=(await session.execute(select(Category).where(Category.user_id==user.id,Category.name==body.key))).scalar_one_or_none()
    if record is None:
        record=Category(user_id=user.id,name=body.key,is_default=False)
        session.add(record)
    record.is_archived=body.archived
    await session.commit()
    return await category_catalog(session,user.id)

@router.post('/imports/inspect')
async def inspect_file(body:CsvInspectInput,user=Depends(get_user)):
    try:return inspect_csv(body.content)
    except CsvImportError as error:raise HTTPException(422,str(error))

@router.post('/imports/preview')
async def preview_file(body:CsvPreviewInput,user=Depends(get_user),session=Depends(get_session)):
    try:
        account=await owned_account(session,user,body.account_id)
        result=await preview_csv(session,user,body,account)
    except (ValueError,CsvImportError) as error:raise HTTPException(422,str(error))
    await session.commit()
    return result

@router.post('/imports/{import_id}/confirm')
async def confirm_file(import_id:str,user=Depends(get_user),session=Depends(get_session)):
    try:count=await finish_import(session,import_id,user.telegram_id)
    except CsvImportError as error:raise HTTPException(409,str(error))
    await session.commit()
    return {'count':count}
