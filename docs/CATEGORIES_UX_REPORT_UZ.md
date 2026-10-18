# Kategoriya va subkategoriyalar: bajarilgan ishlar

Sana: 2026-10-18. Branch: `mirzo`.

## Foydalanuvchi uchun

- Sozlamalar → Kategoriyalar: barcha standart, shaxsiy va tarixdagi import kategoriyalari ko‘rinadi. Turli valyutadagi eski yozuvlarning kategoriyalari ham ro‘yxatga kiradi.
- Ro‘yxat ichidan qidirish mumkin. Subkategoriya qidirilsa uning asosiy kategoriyasi bilan birga chiqadi.
- “Yangi kategoriya” tugmasi nom, asosiy kategoriya va ikonka tanlash oynasini ochadi.
- Ikonkani foydalanuvchi 24 ta tayyor vektor belgidan tanlaydi. Rasm/logo faylini yuklash bu o‘zgarishga kirmaydi.
- Har bir asosiy kategoriya yonidagi `+` subkategoriya qo‘shadi; qalam tugmasi tahrirlaydi.
- Asosiy kategoriya nomi yonidagi strelka faqat subkategoriyalar mavjud bo‘lganda chiqadi va ularni ochadi/yopadi.
- Subkategoriya nomi, ikonasi va asosiy kategoriyasini ham tahrirlash mumkin. Ikki daraja qo‘llanadi: asosiy kategoriya → subkategoriya.
- Kirim/chiqim formasida subkategoriya tanlanadi; tagida asosiy kategoriya nomi bor. Qidiruv uning asosiy kategoriyasini ham hisobga oladi.
- Tanlangan ikonka yozuv kartalari, kiritish formasi va tahlilning kategoriya belgilarida ishlatiladi.
- O‘zbekcha va ruscha interfeys mavjud. Foydalanuvchi yozgan maxsus nomlar avtomatik tarjima qilinmaydi.

## Tarix va hisoblar

Nom tahrirlanganda kategoriya ichki kaliti o‘zgarmaydi, ko‘rsatiladigan nom yangilanadi. Shu sabab eski operatsiyalar, pul summalari, bog‘lanishlar va import tarixi qayta yozilmaydi. Standart kategoriya tahriri faqat joriy hisob uchun saqlanadi; boshqa foydalanuvchilarga ta’sir qilmaydi.

Bot keyingi xabarni qayta ishlaganda hisobning maxsus kategoriya nomlarini oladi. Nomlarni bir foydalanuvchidan boshqasiga o‘tkazmaslik uchun bu holat so‘rov doirasida saqlanadi va oxirida tiklanadi.

CSV eksportdagi kategoriya kalitlari moslik uchun saqlandi. Subkategoriyalar kesimida yozuvlar hisoblanadi; asosiy kategoriya ostidagi barcha subkategoriyalarni alohida yig‘uvchi yangi hisobot rejimi bu ish doirasiga qo‘shilmadi.

## UI/UX

Ro‘yxatdagi amallar aniq ajratildi, bosish joylari kamida 44 px. Kategoriya oynasining sarlavhasi/yopish tugmasi tepada, saqlash/bekor qilish pastda qoladi; ichki maydonlar va ikonalar ro‘yxati alohida aylanadi. 320 px ekranda ikonalar 4 ustun, kengroq telefonda 6 ustun bo‘ladi. Kiritish maydonlari 16 px, uzun nomlar satrga o‘raladi.

## Tekshiruvlar

- Python: 67 testdan **62 tasi o‘tdi**, 5 PostgreSQL testi test bazasi manzili berilmagani uchun o‘tkazib yuborildi.
- Frontend: **14/14 test o‘tdi**. TypeScript, production build va `git diff --check` muvaffaqiyatli.
- Yangi backend tekshiruvlari: ikonka va subkategoriyani saqlash, boshqa brauzerda qayta olish, standart kategoriyani faqat o‘z hisobida tahrirlash, tarixdagi summa/kalitning saqlanishi, boshqa hisobga kira olmaslik, takroriy nomlar, o‘z ostiga joylash va uchinchi darajani rad etish.
- Eski `categories` jadvaliga yangi ustunlar qo‘shilishi ikki marta ishga tushirilib, mavjud nom va emoji saqlanishi tekshirildi.
- Botda maxsus nomlarning hisobga tegishliligi va handler xato qilganda kontekstning tiklanishi tekshirildi.
- Lokal izolyatsiyalangan test hisobida kategoriya va ikonka yaratildi, subkategoriya qo‘shildi, ikkalasining nomi tahrirlandi, qayta yuklanganda saqlanishi ko‘rildi. Subkategoriya bilan 1 000,50 UZS test chiqimi saqlandi va kartada yangi nom chiqdi. Haqiqiy foydalanuvchining moliyaviy yozuvlari o‘zgartirilmadi.
- 320/390/768/1440 px kengliklar tekshirildi. Jismoniy telefon va production Telegram botida end-to-end tekshiruv bajarilmadi.

## Fayllar

- `bot/models/category.py`, `bot/database/schema.py`: `display_name` va `parent_name`, eski bazaga mos yangilash.
- `bot/services/categories.py`, `api/schemas.py`, `api/main.py`: hisobga tegishli katalog, yaratish/tahrirlash va daraxt tekshiruvlari. Eski `/api/categories` string ro‘yxati moslik uchun saqlandi; yangi `/api/category-settings` metadatani qaytaradi.
- `bot/services/i18n.py`, `bot/handlers/language.py`: botdagi shaxsiy kategoriya nomlari.
- `web/components/category-manager.tsx`, `category-provider.tsx`, `category-icon.tsx`: kategoriya daraxti, ikonalar va tahrirlash oynasi.
- `web/components/settings.tsx`, `entry-sheet.tsx`, `language-provider.tsx`, `web/app/page.tsx`, `layout.tsx`: sozlamalar, kirim/chiqim va umumiy ko‘rinishlarga ulash.
- `web/app/mobile-focus.css`, `web/lib/translations.ts`: responsive dizayn va ikki til.
- `tests/test_web_api.py`, `tests/test_language.py`: funksional va migratsiya tekshiruvlari.

## Holat

Preview: https://mone-web-theta.vercel.app/?view=settings

Public preview namuna rejimida. Doimiy saqlash va autentifikatsiya lokal test API/bazasida tekshirildi. Asosiy backend va botga yangi kod hali deploy qilinmagan. O‘zgarishlar `mirzo`da, commit/push yoki `main`ga merge bu so‘rov doirasida bajarilmadi.
