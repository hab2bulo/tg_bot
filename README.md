# O'qituvchi Bot â€” Sozlash

## 1. O'rnatish
```bash
pip install -r requirements.txt
```

## 2. Muhit o'zgaruvchilarini sozlash

Bot tokeni va o'qituvchining shaxsiy Telegram ID'sini kodga yozmang. PowerShell'da:
```powershell
$env:BOT_TOKEN = "BotFather bergan yangi token"
$env:TEACHER_ID = "o'qituvchining Telegram ID si"
$env:MINI_APP_URL = "https://yourdomain.com"
```

Bash'da:
```bash
export BOT_TOKEN="BotFather bergan yangi token"
export TEACHER_ID="o'qituvchining Telegram ID si"
export MINI_APP_URL="https://yourdomain.com"
```

## 3. Bot va Mini App serverini ishga tushirish

Loyiha ildiz papkasida faqat bitta jarayonni boshlang:
```bash
python main.py
```

Bu jarayon bot polling va Flask serverini birga ishga tushiradi. `bot.py` yoki `server.py` fayllari loyihada yo'q. `DATABASE_PATH` muhit o'zgaruvchisi berilmasa, baza loyiha papkasidagi `school.db` faylida saqlanadi.

## 4. Mini App ni Telegram ga ulash
- @BotFather â†’ Bot tanlang â†’ Menu Button â†’ Web App URL
- URL: `MINI_APP_URL` qiymatiga teng, HTTPS manzil
- Panelni Telegram ilovasi ichidan oching. Backend Telegram `initData` imzosini tekshiradi va faqat `TEACHER_ID` egasiga ruxsat beradi.

## O'qituvchi o'quvchiga yozishi
- Bot chatida `/start` yuboring va **O'quvchiga yozish** tugmasini bosing.
- Ro'yxatdan o'quvchini tanlang, keyingi xabar yoki mediani yuboring. Reply qilish ham, Mini App ochish ham shart emas.
- Yozishni to'xtatish uchun `/cancel` yuboring.

## Nginx bilan (tavsiya)
```nginx
server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
    }
}
```

## Xavfsizlik
- HTTPS ishlating (Nginx + Let's Encrypt)
- `TEACHER_ID` o'qituvchining shaxsiy Telegram ID'si bo'lishi kerak
- Agar polling `409 Conflict` xatosini qaytarsa, webhookni o'chiring va botning faqat bitta nusxasini ishga tushiring
- Kodga avval yozilgan bot tokeni oshkor bo'lgan bo'lishi mumkin; BotFather'da uni bekor qilib, yangisini muhit o'zgaruvchisida ishlating
