import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock
from sqlalchemy import select, func
import test_web_api
from bot.models import User, Account, Transaction, Transfer, Category, BudgetAlert, RecurringRule, RecurringOccurrence
from bot.services.finance import recurring_due, next_occurrence
from bot.services.finance_worker import finance_tick

class FinanceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_web_api.WebApiTests.asyncSetUp
    asyncTearDown=test_web_api.WebApiTests.asyncTearDown
    payload=test_web_api.WebApiTests.payload

    async def cash(self,currency='UZS'):
        records=(await self.client.get('/api/accounts')).json()
        return next(row for row in records if row['currency']==currency)

    async def test_accounts_backfill_legacy_and_transfers_do_not_change_income_expense(self):
        cash=await self.cash()
        self.assertEqual(Decimal(cash['balance']),Decimal('975.25'))
        card=await self.client.post('/api/accounts',json={'name':'Card','kind':'card','currency':'UZS','opening_balance':'100'})
        self.assertEqual(card.status_code,201)
        key='test-transfer-0001'
        payload={'source_id':cash['id'],'destination_id':card.json()['id'],'source_amount':'200','date':'2026-10-03','request_key':key}
        first=await self.client.post('/api/transfers',json=payload)
        self.assertEqual(first.status_code,201)
        self.assertEqual((await self.client.post('/api/transfers',json=payload)).json(),first.json())
        self.assertEqual((await self.client.post('/api/transfers',json={**payload,'source_amount':'201'})).status_code,409)
        summary=(await self.client.get('/api/summary?start=2026-10-01&end=2026-10-31')).json()
        self.assertEqual(Decimal(summary['income']),Decimal('1000.50'))
        self.assertEqual(Decimal(summary['expense']),Decimal('25.25'))
        self.assertEqual(Decimal(summary['balance']),Decimal('1075.25'))
        accounts=(await self.client.get('/api/accounts')).json()
        self.assertEqual(Decimal(next(item for item in accounts if item['id']==cash['id'])['balance']),Decimal('775.25'))
        self.assertEqual(Decimal(next(item for item in accounts if item['id']==card.json()['id'])['balance']),Decimal('300'))

    async def test_account_ownership_and_currency_conversion_are_explicit(self):
        cash=await self.cash();usd=await self.cash('USD')
        payload={'source_id':cash['id'],'destination_id':usd['id'],'source_amount':'130000','date':'2026-10-03','request_key':'cross-currency-001'}
        self.assertEqual((await self.client.post('/api/transfers',json=payload)).status_code,422)
        self.assertEqual((await self.client.post('/api/transfers',json={**payload,'destination_amount':'10'})).status_code,201)
        self.assertEqual(Decimal((await self.cash('USD'))['balance']),Decimal('-90'))
        async with self.pool.begin() as session:
            foreign=Account(user_id=self.other_id,name='Other',currency='UZS',kind='bank')
            session.add(foreign);await session.flush();foreign_id=foreign.id
        self.assertEqual((await self.client.post('/api/transfers',json={**payload,'destination_id':foreign_id,'request_key':'foreign-transfer-01'})).status_code,404)
        self.assertEqual((await self.client.post('/api/transactions',json=self.payload(account_id=foreign_id))).status_code,409)
        self.assertEqual((await self.client.post('/api/transfers',json={**payload,'destination_id':cash['id']})).status_code,422)

    async def test_archive_hides_parent_children_but_preserves_history(self):
        await self.client.post('/api/categories',json={'name':'Cafe','parent_name':'Еда','icon':'coffee'})
        result=await self.client.post('/api/category-settings/archive',json={'key':'Еда','archived':True})
        self.assertEqual(result.status_code,200)
        self.assertTrue(next(item for item in result.json() if item['name']=='Cafe')['archived'])
        self.assertEqual((await self.client.post('/api/transactions',json=self.payload(category='Cafe'))).status_code,409)
        self.assertEqual((await self.client.patch(f'/api/transactions/{self.own_tx}',json=self.payload(category='Еда',amount='25.25',date='2026-10-02'))).status_code,200)
        self.assertEqual((await self.client.post('/api/category-settings/archive',json={'key':'Cafe','archived':False})).status_code,409)
        restored=await self.client.post('/api/category-settings/archive',json={'key':'Еда','archived':False})
        self.assertFalse(next(item for item in restored.json() if item['name']=='Cafe')['archived'])

    async def test_recurring_month_end_and_repeated_tick_are_idempotent(self):
        cash=await self.cash()
        async with self.pool.begin() as session:
            user=await session.get(User,self.user.id)
            rule=RecurringRule(user_id=user.id,account_id=cash['id'],type='expense',amount=Decimal('200'),category='Еда',description='Monthly',frequency='monthly',next_date=date(2024,1,31),anchor_day=31)
            session.add(rule);await session.flush()
            self.assertEqual(await recurring_due(session,user,date(2024,3,31)),3)
            self.assertEqual(await recurring_due(session,user,date(2024,3,31)),0)
            self.assertEqual(rule.next_date,date(2024,4,30))
            dates=(await session.execute(select(RecurringOccurrence.date).where(RecurringOccurrence.rule_id==rule.id).order_by(RecurringOccurrence.date))).scalars().all()
            self.assertEqual(dates,[date(2024,1,31),date(2024,2,29),date(2024,3,31)])
        self.assertEqual(next_occurrence(date(2026,12,31),'monthly',31),date(2027,1,31))

    async def test_budget_levels_are_unique_and_telegram_is_opt_in(self):
        budget={'month':'2026-10','category':'Еда','currency':'UZS','amount':'30','notify_telegram':False}
        response=await self.client.post('/api/budgets',json=budget)
        self.assertEqual(response.status_code,201)
        self.assertGreater(Decimal(response.json()[0]['percent']),Decimal(80))
        await self.client.post('/api/transactions',json=self.payload(category='Еда',amount='10'))
        await self.client.get('/api/budgets');await self.client.get('/api/budgets')
        async with self.pool() as session:
            self.assertEqual((await session.execute(select(func.count()).select_from(BudgetAlert))).scalar_one(),2)
        bot=AsyncMock()
        await finance_tick(self.pool,bot)
        bot.send_message.assert_not_awaited()
        await self.client.post('/api/budgets',json={**budget,'notify_telegram':True})
        await finance_tick(self.pool,bot);await finance_tick(self.pool,bot)
        self.assertEqual(bot.send_message.await_count,2)
        self.assertTrue(all(call.args[0]==111 for call in bot.send_message.call_args_list))

    async def test_csv_mapping_preview_duplicates_and_confirm(self):
        cash=await self.cash()
        content='When;Value;Kind;Memo\n2026-10-03;50;expense;Lunch\n2026-10-03;50;expense;Lunch\n'
        inspect=await self.client.post('/api/imports/inspect',json={'filename':'test.csv','content':content})
        self.assertEqual(inspect.status_code,200)
        self.assertEqual(inspect.json()['headers'],['When','Value','Kind','Memo'])
        body={'content':content,'filename':'test.csv','account_id':cash['id'],'mapping':{'date':'When','amount':'Value','type':'Kind','description':'Memo'}}
        preview=await self.client.post('/api/imports/preview',json=body)
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual((preview.json()['accepted'],preview.json()['duplicates']),(1,1))
        key=preview.json()['id']
        self.assertEqual((await self.client.post(f'/api/imports/{key}/confirm')).json()['count'],1)
        self.assertEqual((await self.client.post(f'/api/imports/{key}/confirm')).status_code,409)
        repeat=(await self.client.post('/api/imports/preview',json=body)).json()
        self.assertEqual(repeat['accepted'],0)
        self.assertEqual(repeat['duplicates'],2)
        self.assertEqual((await self.client.post('/api/imports/preview',json={**body,'mapping':{'date':'When','amount':'When'}})).status_code,422)

    async def test_backup_additive_restore_and_owner_validation(self):
        backup=await self.client.get('/api/backup')
        self.assertEqual(backup.status_code,200,backup.text)
        body=backup.json()
        self.assertEqual((await self.client.post('/api/backup/preview',json=body)).json()['transactions'],3)
        self.assertEqual((await self.client.delete(f'/api/transactions/{self.own_tx}')).status_code,204)
        result=await self.client.post('/api/backup/restore',json=body)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual((result.json()['restored'],result.json()['skipped']),(1,2))
        self.assertTrue((await self.client.post('/api/backup/restore',json=body)).json()['already_restored'])
        self.assertEqual((await self.client.post('/api/backup/restore',json={**body,'owner':'222'})).status_code,409)
        self.assertEqual((await self.client.post('/api/backup/restore',json={**body,'version':999})).status_code,422)

    async def test_settings_do_not_rewrite_historical_currency(self):
        async with self.pool.begin() as session:
            user=await session.get(User,self.user.id);user.language='uz'
        result=await self.client.patch('/api/preferences',json={'currency':'USD','timezone':'Europe/London','week_start':6,'quick_categories':['Еда','Транспорт']})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['currency'],'USD')
        self.assertEqual(result.json()['timezone'],'Europe/London')
        async with self.pool() as session:
            self.assertEqual((await session.get(Transaction,self.own_tx)).currency,'UZS')
        self.assertEqual((await self.client.patch('/api/preferences',json={'timezone':'Invalid/Zone'})).status_code,422)
        self.assertEqual((await self.client.patch('/api/preferences',json={'quick_categories':['Unknown']})).status_code,422)
        self.assertEqual((await self.client.patch('/api/preferences',json={'timezone':''})).status_code,422)

    async def test_localized_category_names_preserve_keys_and_history(self):
        response=await self.client.post('/api/categories',json={'name':'Test learning','name_uz':'Test ta’lim','name_ru':'Тест учёбы','icon':'science'})
        self.assertEqual(response.status_code,201,response.text)
        created=await self.client.post('/api/transactions',json=self.payload(category='Test learning'))
        self.assertEqual(created.status_code,201,created.text)
        changed=await self.client.patch('/api/category-settings',json={'key':'Test learning','name':'Learning','name_uz':'O‘qish testi','name_ru':'Тест обучения','icon':'brain'})
        self.assertEqual(changed.status_code,200,changed.text)
        item=next(item for item in changed.json() if item['name']=='Test learning')
        self.assertEqual((item['name_uz'],item['name_ru'],item['icon']),('O‘qish testi','Тест обучения','brain'))
        async with self.pool() as session:
            self.assertEqual((await session.get(Transaction,created.json()['id'])).category,'Test learning')
        duplicate=await self.client.post('/api/categories',json={'name':'Another test','name_ru':'Тест обучения'})
        self.assertEqual(duplicate.status_code,409)
        self.assertEqual((await self.client.post('/api/categories',json={'name':'Bad icon','icon':'unknown'})).status_code,422)

    async def test_report_account_and_currency_scope_remain_separate(self):
        cash=await self.cash()
        response=await self.client.get('/api/summary?start=2026-10-01&end=2026-10-31&currency=USD')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(Decimal(response.json()['expense']),Decimal('100'))
        self.assertEqual(response.json()['currency'],'USD')
        scoped=await self.client.get(f'/api/summary?start=2026-10-01&end=2026-10-31&account_id={cash["id"]}')
        self.assertEqual(Decimal(scoped.json()['expense']),Decimal('25.25'))
        self.assertEqual((await self.client.get('/api/summary?account_id=99999')).status_code,404)

    async def test_backup_preserves_repeated_rows_and_pauses_restored_automation(self):
        cash=await self.cash()
        for _ in range(2):
            await self.client.post('/api/transactions',json=self.payload(description='Identical legitimate rows'))
        body=(await self.client.get('/api/backup')).json()
        body['recurring']=[{'account_id':cash['id'],'type':'expense','amount':'10','category':'Еда','description':'Restored test','frequency':'monthly','next_date':'2027-01-01','anchor_day':1,'enabled':True}]
        body['budgets']=[{'month':'2027-01','category':'Еда','currency':'UZS','amount':'100','notify_telegram':True}]
        async with self.pool.begin() as session:
            from sqlalchemy import delete
            await session.execute(delete(Transaction).where(Transaction.user_id==self.user.id,Transaction.description=='Identical legitimate rows'))
        result=await self.client.post('/api/backup/restore',json=body)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['restored'],2)
        async with self.pool() as session:
            self.assertEqual((await session.execute(select(func.count()).select_from(Transaction).where(Transaction.user_id==self.user.id,Transaction.description=='Identical legitimate rows'))).scalar_one(),2)
            self.assertFalse((await session.execute(select(RecurringRule).where(RecurringRule.user_id==self.user.id))).scalar_one().enabled)
            from bot.models import Budget
            self.assertFalse((await session.execute(select(Budget).where(Budget.user_id==self.user.id))).scalar_one().notify_telegram)
