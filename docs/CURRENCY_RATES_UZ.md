# Bepul valyuta kurslari va hisob-kitob tuzatishlari

Sana: 2026-10-19. Ishchi branch: `mirzo`.

## Kurslar

Manba — [O‘zbekiston Markaziy bankining ochiq API’si](https://cbu.uz/uz/arkhiv-kursov-valyut/veb-masteram/). Pullik xizmat yoki yangi API kaliti kerak emas. Tashqi manbaga faqat kurs sanasi yuboriladi; Telegram ID, hisoblar, summalar va yozuvlar yuborilmaydi.

- API’dagi `Nominal` hisobga olinadi: bitta birlik kursi `Rate / Nominal`.
- Hisoblashlar `Decimal`; UZS orqali USD/EUR kabi juftliklar ham hisoblanadi. Yaxlitlash ko‘rsatiladigan yakuniy summada ikki kasrga amalga oshiriladi.
- Kurslar PostgreSQL’da saqlanadi. Joriy sana kursi ishlatilganda ko‘pi bilan har 6 soatda yangilanadi. Tarixiy sanalar alohida saqlanadi. Xatodan keyin qayta urinish 5 daqiqaga cheklanadi.
- Tashqi API ishlamasa, joriy ekvivalent uchun 7 kundan eski bo‘lmagan saqlangan kurs ishlatilishi mumkin; bunda ogohlantirish va haqiqiy kurs sanasi ko‘rsatiladi. Tarixiy konvertatsiyada boshqa kun kursi yashirincha almashtirilmaydi.
- Kerakli valyuta kursi yo‘q bo‘lsa, noto‘liq jami to‘liq balans sifatida ko‘rsatilmaydi.
- Kursning amal qilish sanasi dam olish kunlarida bugundan oldingi sana bo‘lishi mumkin. Kurs rasmiy ma’lumot uchun; bankning xarid/sotuv kursi boshqacha bo‘lishi mumkin.

Website’da: **Sozlamalar → Hisob sozlamalari → Rasmiy valyuta kurslari**. Turli valyutadagi hisoblar bo‘lsa, bosh sahifa va hisoblar oynasida **taxminiy jami ekvivalent** ko‘rinadi. O‘tkazmada **Markaziy bank kursida to‘ldirish** taklif summani beradi; foydalanuvchi bankdagi haqiqiy tushadigan summani o‘zgartiradi va keyin alohida saqlaydi.

Eski operatsiyalarning summasi va valyutasi o‘zgartirilmaydi. Taxminiy ekvivalent alohida hisoblanadi; statistikada turli valyutalar kurs ishlatmasdan qo‘shilmaydi.

## Tuzatilgan muammolar

- Bot tasdiqlashidan keyingi qoldiq har bir valyuta bo‘yicha, boshlang‘ich qoldiq va o‘tkazmalarni hisobga olib chiqariladi.
- Matn/ovozda aytilmagan valyuta foydalanuvchi sozlamasidan olinadi. Aytilgan valyuta saqlanadi. Sana profilning vaqt mintaqasida olinadi.
- Balansni tenglashtirish aniq hisob va valyutaga tegishli; boshqa hamyon o‘zgarmaydi. Bir nechta hisob ko‘rsatilgan noaniq so‘rov avtomatik bitta hamyonga yig‘ilmaydi.
- Kasrli pul qiymatlari tasdiqlash oynasi va xabarlarda saqlanadi; manfiy yoki noto‘g‘ri kirim/chiqim bloklanadi.
- Tasdiqlash egasi tekshiriladi; bir tugmani parallel bosish ikki yozuv yaratmaydi. Muvaffaqiyat xabari bazaga commit bo‘lgandan keyin yuboriladi.
- Eski Telegram kirish ma’lumotlarining muddati qo‘shimcha autentifikatsiya yo‘lida ham tekshiriladi.
- Aynan bir zaxira fayli keyinchalik o‘chirilgan yozuvlarni yana tiklay oladi; mavjud yozuvlar ko‘paymaydi.
- Byudjet o‘zgargan yoki xarajat tuzatilgan bo‘lsa, eskirgan navbatdagi ogohlantirish yuborilmaydi.
- AI parser xom moliyaviy xabar va to‘liq javobni production logiga yozmaydi.

## Keyingi ustuvor ishlar

1. **HTTPS va haqiqiy Telegram oqimi.** Ochiq HTTPS, domen va port sozlamalari avvalgi kelishuvga ko‘ra bu ishda o‘zgartirilmaydi. Jismoniy iPhone/Android va botdan website’ga kirishni haqiqiy qurilmada tekshirish hali qolgan.
2. **Tasdiqlanmagan bot yozuvlarini doimiy saqlash.** Hozir ular xotirada; bot restart bo‘lsa, eski tasdiqlash kartasi ishlamaydi. Doimiy qoralama va amal qilish muddati kerak.
3. **O‘tkazmani tahrirlash/bekor qilish.** Hozir tarixni ko‘rish va yangi o‘tkazma yaratish bor; xato o‘tkazmani maxsus tuzatish oqimi yo‘q.
4. **`/reset` mazmunini aniqlashtirish.** Eski buyruq operatsiyalar va CSV importlarini o‘chiradi, ammo boshlang‘ich qoldiq, o‘tkazma va avtomatik rejalar qoladi. To‘liq tozalash deb ta’riflash noto‘g‘ri; foydalanuvchi tanlaydigan aniq doira kerak.
5. **Balansni tekislash statistikasini ajratish.** Eski qoida bo‘yicha `Сверка` tuzatishlari kirim/chiqim hisoboti tarkibida. Ularni alohida tuzatish turi sifatida ko‘rsatish keyingi hisob modeli o‘zgarishi bo‘ladi.

## Tekshirish

Haqiqiy CBU javobi, `Nominal`, sanalar, joriy/tarixiy cache, tarmoq xatosi, dublikat cache yaratish, noma’lum valyuta, egaga tegishlilik va asl ledger o‘zgarmasligi uchun testlar qo‘shildi. Botda aralash valyutalar, ikki hisob, kasrlar, ruxsatlar va qayta tasdiqlash sinovlari bor. Frontend testlari, TypeScript va production build ishlatiladi; PostgreSQL parallel testlari CI’da bajariladi.

Izolyatsiyalangan lokal test hisobida haqiqiy kurslar ko‘rindi, 100 000 UZS uchun taklif USD summasi to‘ldirildi va qo‘lda o‘zgartirildi. 390 px oynada gorizontal overflow yo‘q. Bu sintetik ledger sinovi; haqiqiy bank o‘tkazmasi bajarilmaydi.
