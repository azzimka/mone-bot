"""Authenticated reference-rate views. Never rewrites the original ledger."""
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from api.main import get_user, get_session
from bot.services.exchange_rates import RatesUnavailable, UnknownCurrency, cbu_today, money_round
from bot.services.finance import account_balances

router = APIRouter(prefix='/api')


async def rate_book(request: Request, session, on: date | None):
    if on and not date(2000, 1, 1) <= on <= cbu_today():
        raise HTTPException(422, 'Kurs sanasi 2000-yildan bugungacha bo‘lishi kerak.')
    try:
        return await request.app.state.exchange_rates.get(session, on)
    except RatesUnavailable as error:
        raise HTTPException(503, str(error))


@router.get('/exchange-rates')
async def exchange_rates(request: Request, base: str = Query(default='UZS', pattern=r'^[A-Z]{3}$'),
                         on: date | None = None, user=Depends(get_user), session=Depends(get_session)):
    book = await rate_book(request, session, on)
    try:
        result = {**book.metadata(), 'base': base, 'rates': [
            {'currency': code, 'rate': str(book.ratio(code, base))}
            for code in sorted(book.rates)]}
    except UnknownCurrency as error:
        raise HTTPException(422, str(error))
    await session.commit()
    return result


@router.get('/exchange-rates/quote')
async def quote(request: Request, source: str = Query(pattern=r'^[A-Z]{3}$'),
                destination: str = Query(pattern=r'^[A-Z]{3}$'),
                amount: Decimal = Query(gt=0, max_digits=15, decimal_places=2, allow_inf_nan=False),
                on: date | None = None, user=Depends(get_user), session=Depends(get_session)):
    book = await rate_book(request, session, on)
    try:
        converted = money_round(book.convert(amount, source, destination))
        ratio = book.ratio(source, destination)
    except UnknownCurrency as error:
        raise HTTPException(422, str(error))
    if converted <= 0:
        raise HTTPException(422, 'Konvertatsiya natijasi 0,01 dan kichik.')
    if converted > Decimal('9999999999999.99'):
        raise HTTPException(422, 'Konvertatsiya natijasi maksimal summadan katta.')
    await session.commit()
    return {**book.metadata(), 'source_currency': source, 'destination_currency': destination,
            'amount': str(amount), 'converted': str(converted), 'rate': str(ratio)}


@router.get('/accounts/valuation')
async def valuation(request: Request, base: str | None = Query(default=None, pattern=r'^[A-Z]{3}$'),
                    user=Depends(get_user), session=Depends(get_session)):
    base = base or user.default_currency
    book = await rate_book(request, session, None)
    try:
        book.ratio(base, base)
    except UnknownCurrency as error:
        raise HTTPException(422, str(error))
    balances = await account_balances(session, user)
    total, missing, items = Decimal(0), [], []
    for account in balances:
        try:
            converted = book.convert(Decimal(account['balance']), account['currency'], base)
        except UnknownCurrency:
            missing.append(account['currency'])
            continue
        total += converted
        items.append({'id': account['id'], 'name': account['name'], 'balance': account['balance'],
                      'currency': account['currency'], 'equivalent': str(money_round(converted))})
    await session.commit()
    return {**book.metadata(), 'base': base, 'estimated': True,
            'complete': not missing, 'missing_currencies': sorted(set(missing)),
            'total': str(money_round(total)) if not missing else None, 'accounts': items}
