"""Bot language comes from the account, scoped to one asynchronous update."""

from contextvars import ContextVar

current_language: ContextVar[str] = ContextVar("mone_language", default="ru")

UZBEK: dict[str, str] = {
    "📊 Расходы за неделю": "📊 Haftalik chiqimlar",
    "📅 История расходов": "📅 Chiqimlar tarixi",
    "За какой период показать расходы?": "Qaysi davr uchun chiqimlar ko‘rsatilsin?",
    "За день": "Kunlik",
    "За месяц": "Oylik",
    "Выберите месяц · {year}": "Oyni tanlang · {year}",
    "Выберите день · {month}": "Kunni tanlang · {month}",
    "📋 Расходы за {period}": "📋 {period} uchun chiqimlar",
    "Расходов нет.": "Chiqimlar yo‘q.",
    "Итого": "Jami",
    "Страница {page} из {pages}": "{page} / {pages}-sahifa",
    "📅 Выбрать день": "📅 Kun tanlash",
    "📅 Выбрать месяц": "📅 Oy tanlash",
    "Некорректная дата.": "Sana noto‘g‘ri.",
    "Меню обновлено.": "Menyu yangilandi.",
    "🎤 Напишите расход или отправьте голосовое.\n✅ Проверьте и подтвердите запись.\n📅 История расходов — отчёт за день или месяц.": "🎤 Chiqimni yozing yoki ovozli xabar yuboring.\n✅ Yozuvni tekshiring va tasdiqlang.\n📅 Chiqimlar tarixi — kunlik yoki oylik hisobot.",
    "📋 Расходы за сегодня": "📋 Bugungi chiqimlar",
    "📅 Расходы за месяц": "📅 Oylik chiqimlar",
    "🚌 Автобус / Метро — 2 000 сум": "🚌 Avtobus / Metro — 2 000 so‘m",
    "🚌 *2 000 {p1}* — записано!\n_Транспорт сегодня: {p3} раз · {p5}_": "🚌 *2 000 {p1}* — saqlandi!\n_Bugungi transport: {p3} marta · {p5}_",
    "📊 *Расходы за неделю*\n\nЗа последние 7 дней расходов нет.": "📊 *Haftalik chiqimlar*\n\nOxirgi 7 kunda chiqimlar yo‘q.",
    "📊 *Расходы за последние 7 дней*\n": "📊 *Oxirgi 7 kunlik chiqimlar*\n",
    "← сегодня": "← bugun",
    "\n💸 *Итого за неделю: {p1}*": "\n💸 *Haftalik jami: {p1}*",
    "🗑 Да, удалить всё": "🗑 Ha, barchasini o‘chirish",
    "❌ Отмена": "❌ Bekor qilish",
    "⚠️ *Удалить все расходы?*\n\nЭто действие удалит все твои записи о расходах. Отменить будет невозможно.\n\nУверен?": "⚠️ *Barcha chiqimlar o‘chirilsinmi?*\n\nBarcha chiqim yozuvlaringiz o‘chiriladi. Buni ortga qaytarib bo‘lmaydi.\n\nTasdiqlaysizmi?",
    "🗑 *Все расходы удалены.*\n\nМожешь начинать с чистого листа! 🆕": "🗑 *Barcha chiqimlar o‘chirildi.*\n\nYangidan boshlashingiz mumkin. 🆕",
    "✅ Отменено. Данные не удалены.": "✅ Bekor qilindi. Ma’lumotlar o‘chirilmadi.",
    "Понедельник": "Dushanba",
    "Вторник": "Seshanba",
    "Среда": "Chorshanba",
    "Четверг": "Payshanba",
    "Пятница": "Juma",
    "Суббота": "Shanba",
    "Воскресенье": "Yakshanba",
    "Январь": "Yanvar",
    "Февраль": "Fevral",
    "Март": "Mart",
    "Апрель": "Aprel",
    "Май": "May",
    "Июнь": "Iyun",
    "Июль": "Iyul",
    "Август": "Avgust",
    "Сентябрь": "Sentabr",
    "Октябрь": "Oktabr",
    "Ноябрь": "Noyabr",
    "Декабрь": "Dekabr",
    "← Назад": "← Orqaga",
    "Дальше →": "Keyingi →",
    "⚠️ Не удалось распознать голосовое сообщение. Попробуйте ещё раз или напишите текстом.": "⚠️ Ovozli xabarni tushunib bo‘lmadi. Qayta yuboring yoki matn bilan yozing.",
    "🎤 *Распознано:* _{p1}_": "🎤 *Aniqlandi:* _{p1}_",
    "⚠️ Не удалось распознать расходы в тексте. Бот ведёт только учёт расходов — например: «Кофе 25 тысяч».": "⚠️ Xabardan chiqim topilmadi. Bot faqat chiqimlarni hisoblaydi — masalan: «Qahva 25 ming».",
    "⚠️ Не удалось распознать расходы в вашем сообщении. Бот ведёт только учёт расходов — например: «Кофе 25000».": "⚠️ Xabardan chiqim topilmadi. Bot faqat chiqimlarni hisoblaydi — masalan: «Qahva 25000».",
    "✅ Верно": "✅ To‘g‘ri",
    "❌ Отменить": "❌ Bekor qilish",
    "*{p1} из {p3}*\n": "*{p1} / {p3}*\n",
    "❌ Произошла ошибка при обработке голосового сообщения. Попробуйте ещё раз.": "❌ Ovozli xabarni qayta ishlashda xatolik. Qayta urinib ko‘ring.",
    "❌ Произошла ошибка при обработке сообщения. Попробуйте ещё раз.": "❌ Xabarni qayta ishlashda xatolik. Qayta urinib ko‘ring.",
    "❌ Данная операция уже обработана или устарела.": "❌ Bu operatsiya allaqachon ko‘rib chiqilgan yoki eskirgan.",
    "Расход": "Chiqim",
    "✅ Успешно сохранено!": "✅ Saqlandi!",
    "❌ Операция отменена.": "❌ Operatsiya bekor qilindi.",
    "Отменено": "Bekor qilindi",
    "📅 *Отчет за {p1}*\n\n": "📅 *{p1} hisoboti*\n\n",
    "📤 *Расходы:*\n": "📤 *Chiqimlar:*\n",
    "📊 *Итоги дня:*\n": "📊 *Kunlik natija:*\n",
    "📊 *Отчет: {p1}*\n\n": "📊 *Hisobot: {p1}*\n\n",
    "📉 *Структура расходов:*\n": "📉 *Chiqimlar tarkibi:*\n",
    "📈 *Сводка:*\n": "📈 *Umumiy natija:*\n",
    "Всего расходов: {p1}": "Jami chiqim: {p1}",
    "Не указана корректная сумма.": "To‘g‘ri summa kiritilmagan.",
    "Неоднозначная сумма: используйте 1 234,56 или 1234.56.": "Summa noaniq: 1 234,56 yoki 1234.56 shaklida yozing.",
    "Сумма должна быть числом с максимум двумя знаками после запятой.": "Summa son bo‘lishi va verguldan keyin ko‘pi bilan 2 raqamga ega bo‘lishi kerak.",
    "Некорректная сумма.": "Summa noto‘g‘ri.",
    "Сумма выходит за допустимый диапазон.": "Summa ruxsat etilgan chegaradan tashqarida.",
}

RUSSIAN: dict[str, str] = {
    "Til saqlandi.": "Язык сохранён.",
}


def tr(key: str, **values) -> str:
    dictionary = UZBEK if current_language.get() == "uz" else RUSSIAN
    return dictionary.get(key, key).format_map(values) if values else dictionary.get(key, key)


def button_variants(key: str) -> set[str]:
    return {key, UZBEK.get(key, key)}


CATEGORY_LABELS = {
    "Еда": "Oziq-ovqat",
    "Транспорт": "Transport",
    "Жильё": "Uy-joy",
    "Одежда": "Kiyim",
    "Развлечения": "Hordiq",
    "Здоровье": "Salomatlik",
    "Образование": "Ta’lim",
    "Работа": "Ish",
    "Связь": "Aloqa",
    "Подарки": "Sovg‘alar",
    "Переводы": "O‘tkazmalar",
    "Другое": "Boshqa",
}

current_category_names: ContextVar[dict[str, str] | None] = ContextVar("current_category_names", default=None)


def category_label(name: str) -> str:
    customized = (current_category_names.get() or {}).get(name)
    if customized:
        return customized
    return CATEGORY_LABELS.get(name, name) if current_language.get() == "uz" else name
