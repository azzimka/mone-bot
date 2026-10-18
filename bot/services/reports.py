from bot.services.i18n import category_label, tr, button_variants
from datetime import datetime
from typing import Dict, Any, List
from .ai_parser import ParsedTransaction

class ReportService:
    def format_amount(self, amount: float, currency: str) -> str:
        """Formats amount with proper separators and currency symbol."""
        formatted_amount = f"{amount:,.0f}".replace(",", " ")
        return f"{formatted_amount} {currency}"

    def format_daily_report(self, transactions: List[Dict[str, Any]], total_income: float, total_expense: float, currency: str = 'UZS') -> str:
        date_str = datetime.now().strftime("%d.%m.%Y")
        report = tr('📅 *Отчет за {p1}*\n\n' ,p1=f'{date_str}')
        
        income_txs = [t for t in transactions if t['type'] == 'income']
        expense_txs = [t for t in transactions if t['type'] == 'expense']
        
        if income_txs:
            report += tr('📥 *Доходы:*\n')
            for t in income_txs:
                amount_str = self.format_amount(t['amount'], currency)
                report += f"➕ {t['category']} ({t['description']}): {amount_str}\n"
            report += "\n"
            
        if expense_txs:
            report += tr('📤 *Расходы:*\n')
            for t in expense_txs:
                amount_str = self.format_amount(t['amount'], currency)
                report += f"➖ {t['category']} ({t['description']}): {amount_str}\n"
            report += "\n"
            
        net = total_income - total_expense
        report += tr('📊 *Итоги дня:*\n')
        report += tr('Доход: {p1}\n' ,p1=f'{self.format_amount(total_income, currency)}')
        report += tr('Расход: {p1}\n' ,p1=f'{self.format_amount(total_expense, currency)}')
        report += tr('Остаток: {p1}' ,p1=f'{self.format_amount(net, currency)}')
        
        return report

    def format_period_report(self, category_summary: Dict[str, float], total_income: float, total_expense: float, period_name: str, currency: str = 'UZS') -> str:
        report = tr('📊 *Отчет: {p1}*\n\n' ,p1=f'{period_name}')
        
        if category_summary:
            report += tr('📉 *Структура расходов:*\n')
            for cat, amount in sorted(category_summary.items(), key=lambda x: x[1], reverse=True):
                percentage = (amount / total_expense) * 100 if total_expense > 0 else 0
                bars_count = int(percentage / 10)
                bars = "▓" * bars_count + "░" * (10 - bars_count)
                amount_str = self.format_amount(amount, currency)
                report += f"{cat}: {amount_str}\n{bars} {percentage:.1f}%\n\n"
            
        balance = total_income - total_expense
        report += tr('📈 *Сводка:*\n')
        report += tr('Всего доходов: {p1}\n' ,p1=f'{self.format_amount(total_income, currency)}')
        report += tr('Всего расходов: {p1}\n' ,p1=f'{self.format_amount(total_expense, currency)}')
        report += tr('Баланс: {p1}' ,p1=f'{self.format_amount(balance, currency)}')
        
        return report

    def format_transaction_confirmation(self, parsed: ParsedTransaction, voice_text: str = "") -> str:
        amount = self.format_amount(parsed.amount, parsed.currency)
        if parsed.type == "reconcile":
            return tr("⚖️ *Сверка баланса*\n\n") + amount + "\n" + tr("Приравнять баланс в боте к этой сумме?")
        kind = tr("Доход") if parsed.type == "income" else tr("Расход")
        emoji = "📥" if parsed.type == "income" else "📤"
        lines = [f"{emoji} {kind}: *{amount}*", f"📂 {category_label(parsed.category)}"]
        if parsed.description:
            lines.append(f"📝 {parsed.description}")
        return "\n".join(lines)
