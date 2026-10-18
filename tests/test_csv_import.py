import unittest
from datetime import date
from decimal import Decimal

from bot.services.csv_import import (
    CsvImportError, MAX_FILE_BYTES, MAX_ROWS, categorize, format_preview, parse_csv,
)


class CsvParserTests(unittest.TestCase):
    def test_uzbek_headers_decimal_comma_and_categories(self):
        preview = parse_csv((
            "sana;turi;summa;valyuta;kategoriya;izoh\n"
            "01.10.2026;kirim;5000000;UZS;;Oylik\n"
            "02.10.2026;chiqim;25 000,50;UZS;;Kofe\n"
            "03.10.2026;chiqim;30000;UZS;Maxsus;Taksi\n"
        ).encode())
        self.assertEqual(preview.transactions[0].category, "Зарплата")
        self.assertEqual(preview.transactions[1].amount, Decimal("25000.50"))
        self.assertEqual(preview.transactions[1].category, "Еда")
        self.assertEqual(preview.transactions[2].category, "Maxsus")
        self.assertEqual(preview.transactions[0].date, date(2026, 10, 1))
        self.assertFalse(preview.inferred_types)

    def test_encodings_delimiters_quotes_and_multiline(self):
        for encoding in ("utf-8-sig", "cp1251"):
            for separator in (",", ";", "\t"):
                with self.subTest(encoding=encoding, separator=separator):
                    content = separator.join(("дата", "тип", "сумма", "описание")) + "\r\n"
                    content += separator.join(("2026-10-01", "расход", "25000", '"Кофе\nс собой"'))
                    tx = parse_csv(content.encode(encoding)).transactions[0]
                    self.assertEqual(tx.category, "Еда")
                    self.assertIn("\n", tx.description)

    def test_signed_amounts_are_explicit_in_preview(self):
        preview = parse_csv(b"date,amount\n2026-10-01,+100\n2026-10-02,-25.50\n")
        self.assertEqual([t.type for t in preview.transactions], ["income", "expense"])
        self.assertEqual(preview.transactions[1].amount, Decimal("25.50"))
        self.assertIn("столбца type нет", format_preview(preview))

    def test_separate_income_expense_columns(self):
        txs = parse_csv(b"sana,kirim,chiqim\n2026-10-01,100,\n2026-10-02,,20\n").transactions
        self.assertEqual([t.type for t in txs], ["income", "expense"])
        self.assertEqual([t.amount for t in txs], [Decimal(100), Decimal(20)])

    def test_negative_expense_becomes_positive_ledger_amount(self):
        tx = parse_csv(b"date,type,amount\n2026-10-01,expense,-25\n").transactions[0]
        self.assertEqual(tx.amount, Decimal(25))

    def test_rejects_invalid_or_ambiguous_amounts(self):
        for amount in ("0", "NaN", "Infinity", "1.234", "1e5", "99999999999999", "25k", "--25"):
            with self.subTest(amount=amount), self.assertRaises(CsvImportError):
                parse_csv(f"date,type,amount\n2026-10-01,expense,{amount}".encode())
        with self.assertRaises(CsvImportError):
            parse_csv(b'date;amount\n2026-10-01;1,000\n')

    def test_rejects_conflicting_type(self):
        for row in ("income,-10", "unknown,10", ",10"):
            with self.subTest(row=row), self.assertRaises(CsvImportError):
                parse_csv(f"date,type,amount\n2026-10-01,{row}".encode())

    def test_requires_unambiguous_dates(self):
        for value in ("10/01/2026", "2026-02-30", "", "not a date"):
            with self.subTest(value=value), self.assertRaises(CsvImportError):
                parse_csv(f"date,amount\n{value},10".encode())

    def test_one_bad_row_rejects_whole_file_with_line_number(self):
        with self.assertRaisesRegex(CsvImportError, "Строка 3"):
            parse_csv(b"date,amount\n2026-10-01,100\nbad,20\n2026-10-02,-5\n")

    def test_rejects_duplicate_headers_missing_fields_and_malformed_rows(self):
        for content in (
            "date,amount,summa\n2026-10-01,1,2", "description,amount\ncoffee,10",
            "date,description\n2026-10-01,coffee", "date,amount\n2026-10-01,1,2",
            'date,amount,description\n2026-10-01,10,"unclosed',
        ):
            with self.subTest(content=content), self.assertRaises(CsvImportError):
                parse_csv(content.encode())

    def test_empty_binary_and_size_limits(self):
        for data in (b"", b"\x00\xff", b"date,amount\n", b"a" * (MAX_FILE_BYTES + 1)):
            with self.subTest(size=len(data)), self.assertRaises(CsvImportError):
                parse_csv(data)

    def test_row_limit(self):
        data = b"date,amount\n" + b"2026-10-01,1\n" * MAX_ROWS
        self.assertEqual(len(parse_csv(data).transactions), MAX_ROWS)
        with self.assertRaises(CsvImportError):
            parse_csv(data + b"2026-10-02,1\n")

    def test_rejects_foreign_currency_instead_of_corrupting_totals(self):
        with self.assertRaisesRegex(CsvImportError, "UZS"):
            parse_csv(b"date,amount,currency\n2026-10-01,10,USD\n")
        tx = parse_csv(b"date,amount,currency\n2026-10-01,10,usd\n", "USD").transactions[0]
        self.assertEqual(tx.currency, "USD")

    def test_separate_amounts_must_have_exactly_one_positive_value(self):
        for values in ("10,20", "0,0", "-1,0"):
            with self.subTest(values=values), self.assertRaises(CsvImportError):
                parse_csv(f"date,income,expense\n2026-10-01,{values}\n".encode())

    def test_category_fallback_and_aliases(self):
        self.assertEqual(categorize("Food", "anything"), "Еда")
        self.assertEqual(categorize("", "Yandex taxi"), "Транспорт")
        self.assertEqual(categorize("", "Barbara"), "Другое")
        self.assertEqual(categorize("", "Unrecognized purchase"), "Другое")

    def test_preview_stays_within_telegram_limit(self):
        data = "date,amount,category,description\n" + "\n".join(
            f"2026-10-01,-10,{'x' * 90}{i},{'d' * 2000}" for i in range(15))
        preview = parse_csv(data.encode())
        self.assertLess(len(format_preview(preview)), 4096)


if __name__ == "__main__":
    unittest.main()
