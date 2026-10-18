# Mone moliyaviy funksiyalar relizi

Sana: 2026-10-19. Hosting: Oracle; Vercel loyihasi o‘chirilgan.

## Reliz tarkibi

- Naqd, karta va bank hisoblari, boshlang‘ich qoldiq, alohida valyuta va hisob balanslari. O‘tkazmalar daromad/chiqim statistikasiga kirmaydi; turli valyutadagi o‘tkazmada ikkala summa qo‘lda kiritiladi.
- Eski yozuvlar o‘z summasi va valyutasida saqlanadi; hisob ochilganda mos valyutadagi naqd hisobga biriktiriladi. Turli valyutalar bitta summaga qo‘shilmaydi.
- Kunlik, haftalik va oylik takroriy ledger yozuvlari; pauza/davom ettirish. Haqiqiy bank to‘lovi bajarilmaydi. Oylik takrorlanish oy oxiri va kabisa yilini hisobga oladi.
- Oylik umumiy yoki kategoriya byudjeti, 80%/100% chegaralar. Telegram ogohlantirishi foydalanuvchi alohida yoqqandagina yuboriladi.
- Website CSV import: hisob tanlash, ustunlarni moslash, oldindan ko‘rish, dublikatlarni ajratish va hisobotini yuklash, alohida tasdiqlash. Limit: 1 MB / 2000 qator. Dublikatlar tasdiqlash vaqtida ham qayta tekshiriladi.
- JSON zaxira, mazmunini oldindan ko‘rish va faqat o‘z Telegram hisobiga tiklash. Tiklash mavjud yozuvlarni o‘chirmaydi; avtomatik yozuvlar pauzada, yangi byudjet bildirishnomalari o‘chirilgan holda tiklanadi. JSON nusxa katta server nusxasini almashtirmaydi: veb tiklash 20 000 yozuvgacha.
- Asosiy valyuta, vaqt mintaqasi, hafta boshlanishi va oltitagacha tezkor kategoriya sozlamalari. Valyuta tanlovi eski tarixni konvertatsiya qilmaydi.
- Kategoriya/subkategoriyalarni arxivlash va qayta tiklash; tarix saqlanadi. 112 ikonka, 13 mavzu, ikonka qidiruvi. Bitta kategoriya uchun ixtiyoriy o‘zbekcha/ruscha nomlar; til almashganda tarixdagi kategoriya kaliti o‘zgarmaydi.
- Moliyaviy boshqaruv sozlamalarda alohida oynalar orqali ochiladi. Mobil formalar, uzun izohlar uchun ko‘p qatorli maydon, scroll va katta tegish joylari qo‘shilgan.

## Tekshiruvlar

- Lokal: 81 backend testdan 73 tasi o‘tdi; 8 PostgreSQL testi lokal test bazasi yo‘qligi sabab o‘tkazildi. CI PostgreSQL 16’da ularni ham bajaradi va Oracle deploy shunga bog‘langan.
- Frontend: 14 test, TypeScript va production build tekshirildi.
- Izolyatsiyalangan test hisobida brauzerdan karta yaratish, o‘tkazma, qoldiqlar va umumiy byudjet saqlash tekshirildi. 390 px oynada gorizontal overflow aniqlanmadi.
- CSV faylini brauzer orqali yuklash kengaytmaning faylga kirish ruxsati sabab yakunlanmadi; import/preview/dublikat/tasdiqlash API testlari mavjud.
- Har deploydan oldin serverda PostgreSQL dump yaratiladi, `pg_restore --list` bilan o‘qilishi tekshiriladi. Bu to‘liq bazani qayta tiklash sinovi hisoblanmaydi. Web JSON tiklash sintetik yozuvlar bilan tekshirilgan.
- Deploydan keyin schema ustunlari, baza bilan bog‘langan API health, frontend/manifest/ikonalar HTTP 200 va botning startup tugashi tekshiriladi.

## Alohida qolgan tekshiruvlar

HTTPS domeni, tarmoq portlari va `WEB_PUBLIC_URL` bu relizda o‘zgartirilmaydi. Haqiqiy Telegram → website oqimi hamda jismoniy iPhone/Android Home Screen, klaviatura va safe-area tekshiruvlari hali bajarilmagan. Viewport va API testlari bu tekshiruvlarning o‘rnini to‘liq bosmaydi. Tashqi zaxira saqlash manzili va to‘liq PostgreSQL tiklash mashqi alohida qolgan.
