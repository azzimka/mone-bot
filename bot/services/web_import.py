"""CSV column mapping and duplicate previews without external services."""
import csv
import io
import json
from decimal import Decimal
from sqlalchemy import select
from bot.models import Transaction
from bot.services.csv_import import ALIASES, MAX_FILE_BYTES, MAX_ROWS, CsvImportError, CsvPreview, normalize, parse_csv
from bot.services.categories import category_catalog
from bot.database.csv_imports import stage_import


def inspect_csv(content: str) -> dict:
    if len(content.encode('utf-8')) > MAX_FILE_BYTES: raise CsvImportError('CSV 1 MB dan oshmasligi kerak.')
    source = content.lstrip('\ufeff')
    try:
        dialect = csv.Sniffer().sniff(source[:8192],delimiters=',;\t')
        reader = csv.reader(io.StringIO(source),dialect)
        headers = next(reader)
        if not headers or len(headers) > 50 or len(set(headers)) != len(headers):
            raise CsvImportError('CSV ustun nomlari takrorlanmasligi kerak.')
        guessed = {field:next((header for header in headers if normalize(header) in {normalize(alias) for alias in aliases}), '') for field,aliases in ALIASES.items()}
        rows = []
        count = 0
        for values in reader:
            if not any(value.strip() for value in values): continue
            count += 1
            if count > MAX_ROWS: raise CsvImportError('Bir CSV faylda ko‘pi bilan 2000 ta yozuv bo‘lishi mumkin.')
            if len(values) != len(headers): raise CsvImportError(f'CSV {reader.line_num}-qatorda ustunlar soni noto‘g‘ri.')
            if len(rows) < 5: rows.append(values)
        return {'headers':headers,'sample':rows,'mapping':guessed,'count':count,'delimiter':dialect.delimiter}
    except (csv.Error,StopIteration) as error:
        raise CsvImportError('CSV faylini o‘qib bo‘lmadi.') from error


def fingerprint(row: dict) -> tuple:
    return (str(row['date']),row['type'],Decimal(str(row['amount'])),row['currency'],row['category'] or '',row['description'] or '',row.get('account_id'))


async def preview_csv(session, user, body, account):
    info = inspect_csv(body.content)
    mapping = {key:value for key,value in body.mapping.items() if value}
    if not set(mapping).issubset(ALIASES) or any(value not in info['headers'] for value in mapping.values()) or len(set(mapping.values())) != len(mapping):
        raise CsvImportError('CSV ustunlarini to‘g‘ri moslang.')
    stream=io.StringIO()
    writer=csv.writer(stream)
    writer.writerow(list(mapping))
    reader=csv.reader(io.StringIO(body.content.lstrip('\ufeff')),delimiter=info['delimiter'])
    next(reader)
    indices=[info['headers'].index(value) for value in mapping.values()]
    for row in reader:
        if any(value.strip() for value in row):writer.writerow([row[index] for index in indices])
    parsed=parse_csv(stream.getvalue().encode('utf-8'),account.currency)
    aliases={label:item['name'] for item in await category_catalog(session,user.id) for label in [item['display_name'],item.get('name_uz'),item.get('name_ru')] if label}
    existing=(await session.execute(select(Transaction).where(Transaction.user_id==user.id,Transaction.account_id==account.id))).scalars().all()
    seen={fingerprint({'date':item.date,'type':item.type,'amount':item.amount,'currency':item.currency,'category':item.category,'description':item.description,'account_id':item.account_id}) for item in existing}
    rows=[];accepted=[];duplicates=0
    from bot.services.finance import check_category
    for number,tx in enumerate(parsed.transactions,2):
        row={**tx.to_dict(),'category':aliases.get(tx.category,tx.category),'account_id':account.id}
        await check_category(session,user.id,row['category'])
        key=fingerprint(row)
        duplicate=key in seen
        if duplicate:duplicates+=1
        seen.add(key)
        rows.append({**row,'row':number,'duplicate':duplicate})
        if not duplicate or not body.skip_duplicates:accepted.append(row)
    if not accepted:return {'id':None,'rows':rows,'duplicates':duplicates,'accepted':0,'total':len(rows)}
    content=json.dumps({'rows':accepted,'skip_duplicates':body.skip_duplicates},sort_keys=True).encode()
    staged=await stage_import(session,user.id,body.filename,content,CsvPreview(body.content,parsed.transactions,parsed.inferred_types))
    staged.rows_json=json.dumps(accepted,ensure_ascii=False)
    staged.options_json=json.dumps({'skip_duplicates':body.skip_duplicates})
    await session.flush()
    return {'id':staged.id,'rows':rows,'duplicates':duplicates,'accepted':len(accepted),'total':len(rows)}
