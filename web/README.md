# Mone website — birinchi versiya

Next.js + TypeScript interfeysi va `api/` ichidagi FastAPI mavjud bot bilan bir xil
PostgreSQL bazasidan foydalanadi. Hisob-kitoblar serverda `Decimal` orqali bajariladi.

## Mavjud imkoniyatlar

- Dashboard: barcha davrlar balansi, tanlangan oyning kirim/chiqim va natijasi.
- Kunlik pul oqimi, kategoriyalar tarkibi va batafsil xarajat tahlili.
- Operatsiyalarni qidirish, turi va oyi bo‘yicha filtrlash, sahifalash.
- Operatsiya qo‘shish, tahrirlash, tasdiqlab o‘chirish va filtrlangan tarixni CSV eksport qilish.
- Telegram botda tasdiqlash orqali kirish; HttpOnly sessiya cookie’lari.
- Kirilgan hisob ma’lumotlari 30 soniyada va oynaga qaytilganda yangilanadi.
- Asosiy valyuta bo‘yicha hisob. Begona valyutalar umumiy summaga qo‘shilmaydi.
- O‘zbekcha, mobilga mos interfeys. Sintetik namuna rejimi haqiqiy hisobdan ajratilgan.

Hozir alohida karta hisoblari, budjetlar, jamg‘arma maqsadlari va website’dan CSV
import yo‘q. CSV import botdagi `/import` orqali ishlaydi. Balans botning mavjud
ledgeridan hisoblanadi; eski «Сверка» yozuvlari ham kirim/chiqim statistikasiga kiradi.
Namuna rejimidagi o‘zgarishlar faqat sahifa xotirasida, yangilanganda tiklanadi.

## Lokal: bitta server orqali

Node.js 22+, Python 3.12 va PostgreSQL kerak. Repozitoriy ildizidagi `.env` ichida
`DATABASE_URL`, `TELEGRAM_BOT_USERNAME` (`@` belgisiz) va
`WEB_PUBLIC_URL=http://localhost:8000` belgilang. Bot uchun odatdagi tokenlar kerak.

```bash
pip install -r requirements-dev.txt
cd web
npm ci
npm run build
cd ..
uvicorn api.main:create_app --factory --host 127.0.0.1 --port 8000
```

Website: http://localhost:8000. Botni boshqa terminalda yangilangan kod bilan
`python -m bot.main` orqali ishga tushiring. Login faqat API va yangilangan bot bir
DATABASE_URL orqali ulanganida ishlaydi. API tokenlar va Groq kalitisiz ishga tushadi;
Telegram tasdiqlashi uchun botning o‘zi ishlayotgan bo‘lishi kerak.

Website ochilganda avval aniq belgilangan namuna rejimi ko‘rinadi. «Hisobni ulash»ni
bosing, botdagi tekshirish kodini brauzerdagi kod bilan solishtiring va tasdiqlang.
Brauzer o‘z hisobingizga avtomatik o‘tadi. So‘rov 5 daqiqa, sessiya 7 kun amal qiladi;
chiqish serverdagi sessiyani ham bekor qiladi. Hech qanday demo user yoki demo
operatsiya bazaga qo‘shilmaydi.

## Interfeysni hot reload bilan rivojlantirish

API’ni `WEB_PUBLIC_URL=http://localhost:3000 uvicorn api.main:create_app --factory --reload --port 8000`
bilan ishga tushiring. `web/.env.example`ni `web/.env.local`ga nusxalang. So‘ng
`web/` ichida `npm run dev` va http://localhost:3000 ni oching. Originlar aniq
mos kelishi kerak: `localhost` bilan `127.0.0.1`ni aralashtirmang.

## Docker

Ildiz `.env` faylida bot username’i va tashqi website manzilini belgilang. Serverda
`WEB_PUBLIC_URL=https://sizning-domeningiz` bo‘lishi shart: shunda cookie’lar Secure
rejimida yuboriladi. Lokal tekshiruv uchun `http://localhost:8000` qabul qilinadi.

```bash
docker compose -f docker-compose.yml -f docker-compose.web.yml up -d --build
```

Web konteyner porti faqat `127.0.0.1:8000`ga bog‘langan. Serverda HTTPS reverse proxy
shu portga yo‘naltiriladi. Bu yangi, ixtiyoriy Compose fayli: mavjud bot deploy
workflow’i website’ni avtomatik joylashtirmaydi. `Dockerfile.web` frontendni build
qiladi va API bilan bitta konteynerda, root bo‘lmagan user orqali xizmat qiladi.

API va bot ishga tushganda yangi login/sessiya jadvallari yaratiladi; mavjud ledger
ustunlari o‘zgarmaydi. PostgreSQL advisory lock parallel startupni tartiblaydi.
Keyingi schema o‘zgarishlari uchun Alembic migratsiyalarini joriy qilish rejalashtirilgan.

## Tekshiruvlar

Ildizda: `python -m unittest discover -s tests -v`.
`web/` ichida: `npm run typecheck` va `npm run build`.

PostgreSQL concurrency testlari uchun `CSV_TEST_POSTGRES_URL`ga test bazasining
`postgresql+asyncpg://...` URL’ini bering. Testlar alohida vaqtinchalik schema
yaratib, o‘zlari tozalaydi. Shu o‘zgaruvchi berilmasa, ular o‘tkazib yuboriladi.

Browser testida haqiqiy hisobga ulanmasdan namuna rejimini ishlating. End-to-end
Telegram tekshiruvi alohida test bot va test bazasi bilan bajarilishi kerak.
