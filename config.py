import os


BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN muhit o'zgaruvchisini kiriting (BotFather tokeni)")

teacher_id = os.environ.get("TEACHER_ID", "").strip()
if not teacher_id:
    raise RuntimeError("TEACHER_ID muhit o'zgaruvchisini kiriting")

try:
    TEACHER_ID = int(teacher_id)
except ValueError as exc:
    raise RuntimeError("TEACHER_ID musbat Telegram user ID bo'lishi kerak") from exc

if TEACHER_ID <= 0:
    raise RuntimeError("TEACHER_ID musbat Telegram user ID bo'lishi kerak")

MINI_APP_URL = os.environ.get("MINI_APP_URL", "http://localhost:5000").strip()
