# Mone hosting holati

2026-10-19.

- Foydalanuvchi so‘roviga binoan Vercel’dagi `mone-web` loyihasi barcha deploylari bilan o‘chirildi. CLI loyiha o‘chirilganini tasdiqladi; eski public manzil HTTP 404 qaytardi.
- Yagona frontend Oracle’da FastAPI bilan birga ishlaydi. `Dockerfile.web` Next.js statik buildini yaratadi; API o‘sha fayllarga xizmat qiladi. Bot va API umumiy PostgreSQL bazasidan foydalanadi.
- Oracle deploy `9283a9c` holatida muvaffaqiyatli yakunlangan va baza bilan bog‘langan ichki health tekshiruvi o‘tgan. Keyingi lokal funksiyalar hali bu deployga kirmagan.
- Repozitoriyda Vercel’ga avtomatik deploy workflow’i yo‘q. Vercel loyihasini qayta yaratish yoki unga deploy qilish kerak emas.
- Oracle uchun ochiq HTTPS domeni va 80/443 portlarini sozlash hali bajarilmagan. Avtomatik xavfsizlik tekshiruvi bu production o‘zgarishlar uchun alohida rozilik so‘ragan; foydalanuvchining tushuntirish so‘rashi tasdiq hisoblanmaydi.

HTTPS konfiguratsiyasi lokal draft sifatida `deploy/` ichida tayyorlangan. Internetga chiqarish tasdiqlanib, tashqi health va Telegram orqali kirish tekshirilmaguncha tayyor ommaviy havola deb e’lon qilinmaydi. Vercel loyihasini o‘chirish Oracle bazasi, bot yoki frontend kodini o‘chirmaydi.
