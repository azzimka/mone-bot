from bot.services.i18n import category_label, tr, button_variants
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List
from .ai_parser import ParsedTransaction

class ReportService:
    def format_amount(self, amount: Decimal | float | int, currency: str) -> str:
        """Formats amount with proper separators and currency symbol."""
        formatted_amount = f"{Decimal(str(amount)):,.2f}".rstrip("0").rstrip(".").replace(",", " ")
        return f"{formatted_amount} {currency}"

    def format_daily_report(self, transactions: List[Dict[str, Any]], total_expense: float, currency: str = 'UZS') -> str:
        date_str = datetime.now().strftime("%d.%m.%Y")
        report = tr('📅 *Отчет за {p1}*\n\n' ,p1=f'{date_str}')

        expense_txs = [t for t in transactions if t['type'] == 'expense']

        if expense_txs:
            report += tr('📤 *Расходы:*\n')
            for t in expense_txs:
                amount_str = self.format_amount(t['amount'], currency)
                report += f"➖ {t['category']} ({t['description']}): {amount_str}\n"
            report += "\n"

        report += tr('📊 *Итоги дня:*\n')
        report += tr('Всего расходов: {p1}' ,p1=f'{self.format_amount(total_expense, currency)}')

        return report

    def format_period_report(self, category_summary: Dict[str, float], total_expense: float, period_name: str, currency: str = 'UZS') -> str:
        report = tr('📊 *Отчет: {p1}*\n\n' ,p1=f'{period_name}')

        if category_summary:
            report += tr('📉 *Структура расходов:*\n')
            for cat, amount in sorted(category_summary.items(), key=lambda x: x[1], reverse=True):
                percentage = (amount / total_expense) * 100 if total_expense > 0 else 0
                bars_count = int(percentage / 10)
                bars = "▓" * bars_count + "░" * (10 - bars_count)
                amount_str = self.format_amount(amount, currency)
                report += f"{cat}: {amount_str}\n{bars} {percentage:.1f}%\n\n"

        report += tr('📈 *Сводка:*\n')
        report += tr('Всего расходов: {p1}' ,p1=f'{self.format_amount(total_expense, currency)}')

        return report

    def format_transaction_confirmation(self, parsed: ParsedTransaction, voice_text: str = "") -> str:
        amount = self.format_amount(parsed.amount, parsed.currency)
        lines = [f"📤 {tr('Расход')}: *{amount}*", f"📂 {category_label(parsed.category)}"]
        if parsed.description:
            lines.append(f"📝 {parsed.description}")
        return "\n".join(lines)
