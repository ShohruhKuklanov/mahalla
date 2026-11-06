# Mahalla — umumiy virtual 3D shahar (MVP)

Bu papkada ishlaydigan MVP bor: 3D shahar (brauzerda) va uni boshqaradigan server (Node.js + PostgreSQL).
O‘yinchilar kiradi, nik tanlaydi, yer sotib oladi, bino quradi, daromad yig‘adi va yerini sotadi.
Barcha o‘zgarishlar boshqa o‘yinchilarga darhol (WebSocket) ko‘rinadi.

## 1. Kompyuterda sinab ko‘rish (5 daqiqa)

Kerak: **Node.js 20+** (nodejs.org). Boshqa hech narsa o‘rnatish shart emas — ma’lumotlar bazasi avtomatik ishga tushadi.

```bash
npm install
DAY_SECONDS=360 npm run dev     # o‘yin kuni = 6 daqiqa, daromadni tez ko‘rish uchun
```

Brauzerda oching: **http://localhost:3000** → “Sinov uchun kirish” ga istalgan ism yozing → nik tanlang → “Yer top”.
Telefonda sinash: kompyuter va telefon bitta Wi-Fi’da bo‘lsa, `http://<kompyuter-IP>:3000`.

Windows’da: `set DAY_SECONDS=360 && npm run dev`.

## 2. Sinovlar

```bash
npm test
```

15 ta uchidan-uchigacha sinov haqiqiy PostgreSQL’da ishlaydi. Ular quyidagilarni tekshiradi:

- 20 kishi bir vaqtda bitta yerni sotib olmoqchi bo‘lsa, faqat bittasi oladi va boshqalarning tangasi yo‘qolmaydi.
- Tugma ikki marta bosilsa ham pul bir marta yechiladi.
- Uchastka limiti (3 ta), tanga yetmasligi, zona qoidalari va ruxsat etilgan ranglar.
- Daromad 1 kundan ortiq yig‘ilmaydi.
- Bozor: narx oralig‘i, yangi hisob cheklovi, 5% komissiya, bino yer bilan birga o‘tishi.
- Nik qoidalari, shikoyat, moderatsiya va bloklash.
- Har bir hamyon balansi tranzaksiyalar yig‘indisiga teng.

## 3. Render.com'ga joylash (eng oson)

1. Kodni GitHub repozitoriyiga yuklang.
2. render.com → **New → Blueprint** → repozitoriyni tanlang → **Apply**. `render.yaml` server va PostgreSQL'ni o‘zi yaratadi.
3. 3–5 daqiqadan keyin `https://mahalla-xxxx.onrender.com` ochiladi. Kirish "Mehmon sifatida" (`GUEST_LOGIN=1`).
4. Keyinroq Telegram: @BotFather → bot → `/setdomain` → onrender domeni; Render → Environment → `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_NAME`.

Bepul tarif: 15 daqiqa kirilmasa sayt "uxlaydi" (keyingi ochilish ~1 daqiqa); bepul baza **30 kundan keyin tugaydi** (14 kun ichida pullik tarifga o‘tkazish kerak, aks holda ma’lumot o‘chadi). Haqiqiy foydalanuvchilar kelganda Starter tariflariga o‘ting.

## 4. O‘z serveringizga chiqarish (Docker)

Eng sodda yo‘l — Docker o‘rnatilgan har qanday VPS (2 vCPU, 4 GB yetadi):

```bash
cp .env.example .env            # TELEGRAM_BOT_TOKEN va TELEGRAM_BOT_NAME ni yozing
docker compose up -d            # PostgreSQL + server, http://SERVER-IP:3000
```

Keyin:
1. **Domen va HTTPS:** oldiga Caddy yoki Nginx qo‘ying (Caddy HTTPS’ni o‘zi oladi). Telegram kirishi faqat HTTPS domen bilan ishlaydi.
2. **Telegram kirish:** @BotFather → `/newbot` → token’ni `.env` ga yozing → `/setdomain` → saytingiz domeni.
3. **Admin tayinlash:** o‘zingiz kirib nik tanlagach, bazada:
   `update users set role='admin' where nickname='sizning_nik';`
4. **Zaxira nusxa:** `scripts/backup.sh` ni har kuni cron bilan ishga tushiring va nusxani boshqa joyga ko‘chiring. Oyiga bir marta zaxiradan tiklab ko‘ring.
5. **Shaxsiy ma’lumotlar:** O‘zbekiston foydalanuvchilari ma’lumotlarini mamlakat ichidagi serverda saqlash talabini yurist bilan tekshiring.

## 5. Tuzilma

```
web/index.html        3D mijoz (Babylon.js). Server yo‘q joyda o‘zi “demo rejim”da ishlaydi
src/server.ts         API marshrutlari, sessiya, WebSocket, xatolar
src/game.ts           pul va mulk qoidalari: sotib olish, qurish, daromad, bozor (hammasi tranzaksiyada)
src/economy.ts        shahar xaritasi, zonalar, bino shablonlari, narx formulalari
src/auth.ts           Telegram tekshiruvi, sessiyalar, yangi o‘yinchiga 10 000 tanga
src/nickname.ts       nik qoidalari va so‘z filtri
src/seed.ts           shaharni (1 216 uchastka) va namuna qo‘shnilarni yaratish
migrations/           ma’lumotlar bazasi sxemasi
test/                 uchidan-uchigacha sinovlar
```

## 6. API (qisqacha)

| Usul | Manzil | Nima qiladi |
| --- | --- | --- |
| GET | /api/city | butun shahar: uchastkalar, binolar, narxlar |
| POST | /api/auth/telegram · /api/auth/guest · /api/auth/dev | kirish (guest — beta uchun, dev — faqat lokal sinovda) |
| GET | /api/me | balans, mulklar, to‘plangan daromad |
| POST | /api/me/nickname | nik + avatar + 16+ tasdig‘i |
| POST | /api/plots/:id/buy | yer (yoki sotuvdagi mulk) sotib olish · `Idempotency-Key` sarlavhasi |
| POST | /api/plots/:id/build | bino qurish |
| POST | /api/me/collect | daromadni yig‘ish |
| POST / DELETE | /api/plots/:id/list | sotuvga qo‘yish / olish |
| POST | /api/plots/:id/like · /api/reports | yoqdi · shikoyat |
| GET / POST | /api/admin/reports · /api/admin/action | moderatsiya (ban, nikni o‘zgartirish, binoni yashirish) |
| WS | /ws | uchastka o‘zgarishlari real vaqtda |

Narxlar, limitlar va komissiyani kodni o‘zgartirmasdan `economy_config` jadvalida sozlash mumkin.

## 7. Hali yo‘q (keyingi qadamlar)

- Google va SMS orqali kirish (hozir Telegram + sinov kirishi).
- Haqiqiy 3D rassom modellari (glTF). Hozir binolar kod bilan yasalgan.
- Ijara, mulk solig‘i, do‘stlar va shaxsiy xabarlar (reja hujjatidagi 2-bosqich).
- Ko‘p serverga kengayish uchun Redis. Hozir 1 server bir necha yuz onlayn o‘yinchini ko‘taradi.
