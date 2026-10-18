# Mone: mobil UI/UX va bot bo‘yicha hisobot

Sana: 2026-10-18. Ishchi branch: `mirzo`.

2026-10-19 yangilanishi: eski Vercel frontend loyihasi foydalanuvchi so‘roviga binoan o‘chirildi. Quyidagi hisobot 2026-10-18 tekshiruvlarini qayd etadi; eski preview endi ishlamaydi. Joriy hosting holati: [Oracle hosting](HOSTING_UZ.md).

Bu havolada statik frontend va namuna ma’lumotlari bor. Yangi backend funksiyalari alohida lokal test bazasida tekshirildi. Asosiy bot/API serveriga ushbu ish davomida deploy qilinmadi. O‘zgarishlar hali commit/push qilinmagan va `main`ga kiritilmagan.

## Mobil bosh sahifa

1. Telefonda yuqoridagi “Telegram ulangan” belgisi yashirildi. Hisobga kirilmaganida namuna rejimi va Telegram orqali kirish tugmasi qoldirildi: foydalanuvchi namuna raqamlarini o‘z hisobidagi pul deb tushunmasligi kerak.
2. Header markazida mavjud Mone belgisi va nomi turadi. Logo bosh sahifaga qaytaradi.
3. Mobil bosh sahifadan katta sarlavha, reklama iboralari va tavsiflar olib tashlandi.
4. `+ Kirim` va `− Chiqim` ekran pastiga `position: fixed` bilan joylashtirildi. Tegishli tur oldindan tanlangan forma ochiladi. Tugmalar 64 px balandlikda, iPhone safe-area hisobga olingan; ro‘yxat oxiri ularning ostida qolmaydi. Ular operatsiyalar va tahlil sahifalarida ham mavjud, sozlamalarda yashiriladi.
5. Davr tanlovi dizaynga mos oynada ochiladi: **Oy / Interval**. Oylar tugmalar orqali, maxsus interval boshlanish va tugash sanalari orqali tanlanadi. Native sana kalendari telefondagi tanish boshqaruvni saqlaydi.
6. “Bugun”, “Oxirgi 7 kun”, “Oy boshidan” tezkor variantlari qo‘shildi. Yon strelkalar oy yoki ayni uzunlikdagi interval bo‘yicha oldinga/orqaga o‘tadi.
7. Hisobot, operatsiyalar, kategoriyalar tahlili va CSV eksport tanlangan sanalarni ishlatadi. Ikkala chegara kuni ham hisobga kiradi. Noto‘g‘ri sanalar va teskari interval uchun tushunarli xabar bor. API chegarasiga mos maksimal farq 3660 kun.
8. Uzoq interval grafigi 93 kundan oshsa oylar bo‘yicha yig‘iladi; qisqa davrda kunlik ko‘rinish saqlanadi. Yozuv bo‘lmagan kunlar nol bilan to‘ldiriladi.
9. Mobil sahifada balans to‘liq kenglikda, kirim va chiqim yonma-yon. Grafiklar alohida “Tahlil va hisobotlar” bo‘limiga ko‘chirildi. Bosh sahifada so‘nggi 5 ta yozuv qoladi; “Barchasi” to‘liq tarixni ochadi.
10. Maqsadsiz workspace dropdown, yordam tugmasi va takroriy reklama bloklari olib tashlandi. Sidebar’dagi to‘rtta asosiy yo‘nalish ishlaydi: bosh sahifa, operatsiyalar, tahlil, sozlamalar. URL va brauzerning orqaga tugmasi ham mos ishlaydi.
11. Telefon kartalaridagi izoh ixcham ko‘rsatiladi; kartani bosish to‘liq izoh va tahrirlash formasini ochadi. Forma ichida summa, kategoriya, izoh va sana ketma-ket joylashgan; saqlash tugmasi pastda qoladi.
12. Tegish joylari, maydonlar, matn o‘lchamlari va kontrast yaxshilandi. Sana va kiritish maydonlari kamida 16 px; foydalanuvchining sahifani kattalashtirishi bloklanmaydi.

### “Davr natijasi” nima edi?

Bu **tanlangan davrdagi kirim − chiqim**. U umumiy balans bilan bir xil tushuncha emas. Nom desktopda “Davrdagi farq” qilib aniqlashtirildi, formulasi saqlandi; mobil ekranda alohida karta yashirildi. “Joriy balans” barcha yozuvlar asosida hisoblanadi. Davr almashtirilganda balans o‘zgarmaydi, davriy kirim/chiqim o‘zgaradi.

### Yuborilgan rasmlardagi down icon va tartib

macOS vaqtinchalik screenshot fayllariga kirishni rad etdi, shu sabab rasmlardagi aniq elementni ko‘rib tasdiqlashning imkoni bo‘lmadi. Mavjud ishlayotgan interfeys tekshirildi: maqsadsiz workspace dropdown olib tashlandi; oy/davr strelkalari esa davrni almashtiradi. Endi ochiladigan elementlarning vazifasi nomi va holati bilan ifodalanadi.

## Sozlamalar va umumiy til

- Kategoriya qo‘shish: bo‘sh yoki takroriy nom qabul qilinmaydi. Shaxsiy kategoriya faqat o‘sha hisobga ko‘rinadi va hali operatsiya yozilmagan bo‘lsa ham forma tanlovida chiqadi.
- Til: Uzbek/Russian tanlovi autentifikatsiyalangan foydalanuvchining bazadagi profiliga yoziladi. Yangi brauzerda ham shu hisobning tili olinadi. Foydalanuvchi yozgan izohlar tarjima qilinmaydi.
- Birinchi til tanlovi botda; keyingi o‘zgartirishlar website sozlamalarida. Eski bot til tugmasi saqlangan tanlovni almashtira olmaydi.
- Bot keyingi xabar/callback’da profil tilini o‘qib ishlatadi va menyusini yangilaydi. Website ochiq turganda profilni fokusda va davriy ravishda yangilaydi.
- Ma’lumotlar bo‘limida tanlangan davr uchun CSV eksport, CSV’ni bot orqali import qilish yo‘riqnomasi va telefonga o‘rnatish ko‘rsatmasi bor. Website’da CSV yuklash formasi bu ish doirasida qo‘shilmadi.
- Hisob bo‘limida botni ochish va hisobdan chiqish amallari ishlaydi. Bearer orqali kirilgan sessiyani chiqishda bekor qilish ham tuzatildi.
- Namuna rejimida sozlamalar sinov uchungina: shaxsiy bazaga yozilmaydi va bu foydalanuvchiga ko‘rsatiladi.

## Telegram bot

- Buyruqlar menyusi: `/app`, `/today`, `/import`, `/settings`, `/help`.
- Reply keyboard: ilova, balans, bugun. Ilova manzili sozlangan bo‘lsa ilova tugmasi chiqadi.
- Eski week/month/reset handlerlari moslik uchun saqlandi, asosiy menyuda reklama qilinmaydi.
- Boshlash, yordam va yozuv saqlash xabarlari qisqartirildi; kirim/chiqim, summa, kategoriya va kerakli izoh emoji bilan ajratiladi. Maxsus sticker fayllari yoki sticker pack qo‘shilmadi.
- `/settings` website sozlamalarini ochadi. Til va yangi kategoriya boshqaruvi website orqali bajariladi.
- Ovozli kiritishda saqlangan til ishlatiladi.
- Telegram orqali kirishda tasdiqlash qadami saqlandi; til tanlash loginni avtomatik tasdiqlamaydi.

## PWA va iPhone ikonasi

Mavjud logotip qayta ishlatildi. Yangi brend yaratilmagan. Apple Touch Icon 180×180, PWA 192×192 va 512×512, alohida maskable ikonasi va faviconlar mavjud. Manifest nomi **Mone — shaxsiy moliya kabineti**, qisqa nomi **Mone**, ko‘rinishi **standalone**. Apple metadata va safe-area mosligi qo‘shilgan. Moliyaviy ma’lumotlarni offline keshlash qo‘shilmagan.

iPhone’da: Safari’da HTTPS havolani oching → Share → Add to Home Screen → nomi Mone → mavjud bo‘lsa Open as Web App’ni yoqing → Add. Eski kulrang yorliq bo‘lsa, o‘chirib qayta qo‘shing. Yangi ikonadan ochganda logo va Safari manzil satrisiz rejim tekshiriladi. Android Chrome’da Install app yoki Add to Home screen ishlatiladi.

## Tekshiruvlar

- Python: **62 testdan 57 tasi o‘tdi, 5 tasi PostgreSQL test URL’i berilmagani uchun skip**. Xato yo‘q. Maxsus intervalning ikkala chegarasi, foydalanuvchi/valyuta doirasi, balansning saqlanishi, kategoriya maxfiyligi, til, login va logout tekshirildi.
- Frontend: **14/14 test o‘tdi**. Pul qiymatlari, tarjimalar, kabisa/oy/yil chegaralari, noto‘g‘ri intervallar, nol kunlar va oylik grafik yig‘ilishi tekshirildi.
- TypeScript va Next.js production build muvaffaqiyatli yakunlandi. `git diff --check` xatosiz.
- Brauzerda 320, 390, 768 va 1440 px kengliklar tekshirildi; yon tomonga overflow aniqlanmadi. 320×568 ekranda forma va interval oynasi tekshirildi.
- Mobil ro‘yxat oxirgi kartasining pastki chegarasi 719 px, fixed tugmalar boshlanishi 755 px bo‘ldi: karta tugmalar ostida qolmadi.
- Izolyatsiyalangan lokal bazada kategoriya yaratish, qayta yuklanganda saqlanishi, tilni o‘zgartirish, 25 000,50 UZS test chiqimini saqlash, bir kunlik interval va CSV eksport ko‘rildi. Haqiqiy moliyaviy ma’lumotlar o‘zgartirilmadi.
- Vercel preview yangilandi. Public ikonalar va manifest tekshirildi.
- Haqiqiy iPhone/Android qurilmasida o‘rnatish, klaviatura va Telegram botga end-to-end xabar yuborish tekshirilmagan. Viewport tekshiruvi jismoniy qurilma tekshiruvi o‘rnini to‘liq bosa olmaydi.

## Asosiy o‘zgargan fayllar

- `web/app/page.tsx`, `mobile-focus.css`, `layout.tsx`: navigatsiya, mobil bosh sahifa, fixed tugmalar, hisobot, ikonalar metadata’si.
- `web/components/period-picker.tsx`, `web/lib/period.ts`, `period.test.mjs`: oy/interval va grafik hisoblari.
- `web/components/settings.tsx`, `brand.tsx`, `entry-sheet.tsx`, `dialog.tsx`, `mobile-transactions.tsx`: sozlamalar va mobil kiritish.
- `web/lib/translations.ts`, `web/components/language-provider.tsx`, `web/app/language.css`: ikki til va profilga bog‘lash.
- `api/main.py`, `api/schemas.py`: profil tili, shaxsiy kategoriyalar, sessiyadan chiqish.
- `bot/handlers/language.py`, `commands.py`, `bot/services/i18n.py` va tegishli handler/service fayllari: bot tili va qisqa xabarlar.
- `bot/models/user.py`, `bot/database/schema.py`, `repositories.py`: hisobga bog‘langan til va eski baza mosligi.
- `web/public/`, `web/scripts/generate-icons.mjs`, `web/README.md`: ikonalar, manifest va tekshirish ko‘rsatmalari.
- `tests/test_language.py`, `tests/test_web_api.py`, frontend testlari: funksional tekshiruvlar.

## Keyingi tavsiyalar — hozir qo‘shilmagan

1. **Avval haqiqiy backend va botga deploy**, keyin test hisob bilan Telegram → website → til/kategoriya → yozuv oqimini to‘liq tekshirish.
2. Jismoniy iPhone va Android’da Home Screen, klaviatura, safe-area va uzun izohlarni tekshirish.
3. Kategoriyani arxivlash. Qayta nomlash, ikonka va subkategoriya boshqaruvi keyingi ishda qo‘shildi: `CATEGORIES_UX_REPORT_UZ.md`.
4. Alohida hisoblar: naqd, karta, bank; ular orasidagi o‘tkazmalarni daromad/chiqimga qo‘shmaslik.
5. Takroriy yozuvlar va oylik byudjet/limit ogohlantirishlari.
6. Website’da CSV import preview, ustunlarni moslash va dublikatlar hisobotini ko‘rsatish.
7. Website sozlamalarida kerak bo‘lganda valyuta, vaqt mintaqasi, hafta boshlanishi va tezkor kategoriyalarni boshqarish. Valyutani almashtirish uchun tarixdagi konvertatsiya qoidasi oldindan aniqlanishi kerak.
8. Zaxira nusxa va ma’lumotlarni tiklash jarayoni. Yangi foydalanuvchiga keraksiz sozlamalarni birdan ko‘rsatmaslik.

## Qo‘shimcha: katta summalar

Statistik kartalardagi `white-space: nowrap` sababli uzun summa kesilishi mumkin edi. Qiymatlar endi satrga o‘raladi, valyuta alohida yaxlit birlik sifatida keyingi qatorga o‘ta oladi; mobil raqam o‘lchami kartaning ichki kengligiga moslashadi. Ruscha ajratgichli 10 mln, 100 mln, kasrli va yanada uzun summalar haqiqiy CSS va shriftlar bilan vaqtinchalik lokal maketda 320/390/1440 px kengliklarda tekshirildi: gorizontal kesilish aniqlanmadi. 320 px’da juda uzun summalar bir necha qatorda ko‘rsatiladi. Test maketi deploy fayllaridan olib tashlandi.


## Kategoriyalar bo‘yicha keyingi yangilanish

Ikonka tanlash, mavjud kategoriyalarni tahrirlash va subkategoriya boshqaruvi bajarildi. Yangi tafsilotlar va 67 ta backend tekshiruvi holati: [Kategoriya UI/UX hisoboti](CATEGORIES_UX_REPORT_UZ.md).
