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
        report = f"📅 *Отчет за {date_str}*\n\n"
        
        income_txs = [t for t in transactions if t['type'] == 'income']
        expense_txs = [t for t in transactions if t['type'] == 'expense']
        
        if income_txs:
            report += "📥 *Доходы:*\n"
            for t in income_txs:
                amount_str = self.format_amount(t['amount'], currency)
                report += f"➕ {t['category']} ({t['description']}): {amount_str}\n"
            report += "\n"
            
        if expense_txs:
            report += "📤 *Расходы:*\n"
            for t in expense_txs:
                amount_str = self.format_amount(t['amount'], currency)
                report += f"➖ {t['category']} ({t['description']}): {amount_str}\n"
            report += "\n"
            
        net = total_income - total_expense
        report += f"📊 *Итоги дня:*\n"
        report += f"Доход: {self.format_amount(total_income, currency)}\n"
        report += f"Расход: {self.format_amount(total_expense, currency)}\n"
        report += f"Остаток: {self.format_amount(net, currency)}"
        
        return report

    def format_period_report(self, category_summary: Dict[str, float], total_income: float, total_expense: float, period_name: str, currency: str = 'UZS') -> str:
        report = f"📊 *Отчет: {period_name}*\n\n"
        
        if category_summary:
            report += "📉 *Структура расходов:*\n"
            for cat, amount in sorted(category_summary.items(), key=lambda x: x[1], reverse=True):
                percentage = (amount / total_expense) * 100 if total_expense > 0 else 0
                bars_count = int(percentage / 10)
                bars = "▓" * bars_count + "░" * (10 - bars_count)
                amount_str = self.format_amount(amount, currency)
                report += f"{cat}: {amount_str}\n{bars} {percentage:.1f}%\n\n"
            
        balance = total_income - total_expense
        report += f"📈 *Сводка:*\n"
        report += f"Всего доходов: {self.format_amount(total_income, currency)}\n"
        report += f"Всего расходов: {self.format_amount(total_expense, currency)}\n"
        report += f"Баланс: {self.format_amount(balance, currency)}"
        
        return report

    def format_transaction_confirmation(self, parsed: ParsedTransaction, voice_text: str = "") -> str:
        report = ""
        if voice_text:
            report += f"🗣 _«{voice_text}»_\n\n"
            
        if parsed.type == "reconcile":
            amount_str = self.format_amount(parsed.amount, parsed.currency)
            report += f"⚖️ *Сверка баланса*\n\n"
            report += f"🎯 Фактический остаток: *{amount_str}*\n"
            if parsed.description:
                report += f"📝 Описание: {parsed.description}\n\n"
            report += "Приравнять баланс в боте к этой сумме?"
            return report

        emoji = "📥" if parsed.type == "income" else "📤"
        type_str = "Доход" if parsed.type == "income" else "Расход"
        amount_str = self.format_amount(parsed.amount, parsed.currency)
        
        report += f"✅ *Распознано:*\n"
        report += f"{emoji} Тип: {type_str}\n"
        report += f"💰 Сумма: {amount_str}\n"
        report += f"📂 Категория: {parsed.category}\n"
        report += f"📝 Описание: {parsed.description}\n\n"
        report += "Всё верно?"
        
        return report
