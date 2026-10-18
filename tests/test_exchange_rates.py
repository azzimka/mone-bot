import json
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import httpx
from sqlalchemy import select, func
import test_web_api
from bot.models import ExchangeRateSnapshot, Transaction
from bot.services.exchange_rates import ExchangeRateService, RatesUnavailable, cbu_today, parse_cbu


def payload(day=None):
    day=day or cbu_today()
    return [{'Ccy':code,'Nominal':nominal,'Rate':rate,'Date':day.strftime('%d.%m.%Y')}
            for code,nominal,rate in [('USD','1','12000'),('EUR','1','15000'),('JPY','100','8000')]]


class ExchangeRateTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_web_api.WebApiTests.asyncSetUp
    asyncTearDown=test_web_api.WebApiTests.asyncTearDown

    async def asyncSetUp(self):
        await test_web_api.WebApiTests.asyncSetUp(self)
        self.fetcher=AsyncMock(return_value=payload())
        self.service=ExchangeRateService(self.fetcher)
        self.app.state.exchange_rates=self.service

    async def test_nominal_cross_rates_and_exact_quote(self):
        result=await self.client.get('/api/exchange-rates?base=USD')
        self.assertEqual(result.status_code,200,result.text)
        rates={row['currency']:Decimal(row['rate']) for row in result.json()['rates']}
        self.assertEqual(rates['EUR'],Decimal('1.25'))
        quote=await self.client.get('/api/exchange-rates/quote?source=JPY&destination=UZS&amount=100')
        self.assertEqual(quote.status_code,200,quote.text)
        self.assertEqual(quote.json()['converted'],'8000.00')
        cross=await self.client.get('/api/exchange-rates/quote?source=USD&destination=EUR&amount=10')
        self.assertEqual(cross.json()['converted'],'8.00')
        self.assertEqual(self.fetcher.await_count,1)

    async def test_valuation_separates_originals_and_does_not_change_ledger(self):
        result=await self.client.get('/api/accounts/valuation?base=UZS')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['total'],'-1199024.75')
        self.assertTrue(result.json()['estimated'])
        self.assertTrue(result.json()['complete'])
        async with self.pool() as session:
            entries=(await session.execute(select(Transaction).where(Transaction.user_id==self.user.id))).scalars().all()
            self.assertEqual(len(entries),3)
            self.assertEqual(sorted((row.currency,row.amount) for row in entries),[('USD',Decimal('100')),('UZS',Decimal('25.25')),('UZS',Decimal('1000.50'))])

    async def test_unknown_currency_prevents_partial_total(self):
        await self.client.post('/api/accounts',json={'name':'Unknown test','kind':'cash','currency':'ZZZ','opening_balance':'1'})
        result=await self.client.get('/api/accounts/valuation?base=UZS')
        self.assertEqual(result.status_code,200,result.text)
        self.assertIsNone(result.json()['total'])
        self.assertFalse(result.json()['complete'])
        self.assertEqual(result.json()['missing_currencies'],['ZZZ'])
        self.assertEqual((await self.client.get('/api/exchange-rates?base=ZZZ')).status_code,422)

    async def test_cache_survives_new_service_instance(self):
        self.assertEqual((await self.client.get('/api/exchange-rates')).status_code,200)
        replacement=AsyncMock(side_effect=httpx.ConnectError('network unavailable'))
        self.app.state.exchange_rates=ExchangeRateService(replacement)
        self.assertEqual((await self.client.get('/api/exchange-rates')).status_code,200)
        replacement.assert_not_awaited()
        async with self.pool() as session:
            self.assertEqual((await session.execute(select(func.count()).select_from(ExchangeRateSnapshot))).scalar_one(),1)

    async def test_outage_uses_recent_cache_with_stale_label_and_retry_limit(self):
        yesterday=cbu_today()-timedelta(days=1)
        effective,rates=parse_cbu(payload(yesterday),yesterday)
        async with self.pool.begin() as session:
            session.add(ExchangeRateSnapshot(requested_date=yesterday,effective_date=effective,rates_json=json.dumps({key:str(value) for key,value in rates.items()}),fetched_at=datetime.now(timezone.utc)-timedelta(days=1)))
        self.fetcher.side_effect=httpx.ConnectError('offline')
        first=await self.client.get('/api/exchange-rates')
        self.assertEqual(first.status_code,200,first.text)
        self.assertTrue(first.json()['stale'])
        self.assertEqual(first.json()['effective_date'],yesterday.isoformat())
        self.assertEqual((await self.client.get('/api/exchange-rates')).status_code,200)
        self.assertEqual(self.fetcher.await_count,1)

    async def test_no_cache_or_historical_substitution_returns_unavailable(self):
        self.fetcher.side_effect=httpx.ConnectError('offline')
        self.assertEqual((await self.client.get('/api/exchange-rates')).status_code,503)
        self.assertEqual((await self.client.get('/api/exchange-rates?on=2020-01-01')).status_code,503)

    async def test_invalid_dates_amounts_and_anonymous_requests(self):
        tomorrow=(cbu_today()+timedelta(days=1)).isoformat()
        for query in [f'on={tomorrow}','on=1999-12-31','base=usd','base=123']:
            self.assertEqual((await self.client.get('/api/exchange-rates?'+query)).status_code,422)
        for amount in ['-1','0','NaN','1.234','10000000000000']:
            self.assertEqual((await self.client.get(f'/api/exchange-rates/quote?source=USD&destination=UZS&amount={amount}')).status_code,422)
        self.client.cookies.clear()
        self.assertEqual((await self.client.get('/api/exchange-rates')).status_code,401)
        self.assertEqual((await self.client.get('/api/accounts/valuation')).status_code,401)

    async def test_historical_date_is_requested_and_preserved(self):
        historical=date(2020,1,5)
        effective=date(2020,1,3)
        self.fetcher.return_value=payload(effective)
        result=await self.client.get(f'/api/exchange-rates?on={historical}')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['effective_date'],str(effective))
        self.fetcher.assert_awaited_once_with(historical)

    def test_invalid_payloads_are_not_treated_as_one_to_one_rates(self):
        today=cbu_today()
        for value in [[],{},payload()+payload(),[{'Ccy':'USD','Nominal':'0','Rate':'1','Date':today.strftime('%d.%m.%Y')}],
                      [{'Ccy':'USD','Nominal':'1','Rate':'NaN','Date':today.strftime('%d.%m.%Y')}],payload(today+timedelta(days=1))]:
            with self.assertRaises(RatesUnavailable):parse_cbu(value,today)
