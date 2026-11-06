import hashlib
import hmac
import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl

import requests
from flask import Flask, jsonify, request, send_from_directory

from config import BOT_TOKEN, TEACHER_ID
from db import get_conn, init_db

# ── LOGGING ──
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── TELEGRAM API ──
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
APP_DIR = Path(__file__).resolve().parent
PENDING_TEACHER_MESSAGE = {}
STUDENT_PAGE_SIZE = 10


def tg(method, *, request_timeout=10, **data):
    try:
        r = requests.post(
            f"{TG_API}/{method}", json=data, timeout=request_timeout
        )
        r.raise_for_status()
        result = r.json()
        if not isinstance(result, dict) or not result.get("ok"):
            log.warning("TG API %s xato: %s", method, result)
            return {}
        return result.get("result", {})
    except Exception as e:
        log.error("TG API %s ishlamadi: %s", method, e)
        return {}


def send(chat_id, text, **kwargs):
    return tg("sendMessage", chat_id=chat_id, text=text, **kwargs)


def validate_telegram_init_data(init_data):
    """Return the signed Telegram user object, or None for invalid/stale data."""
    if not init_data or len(init_data) > 8192:
        return None

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            return None
        received_hash = data.pop("hash", "")
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(data.items())
        )
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            return None

        auth_date = int(data["auth_date"])
        now = int(time.time())
        if auth_date > now + 60 or now - auth_date > 86400:
            return None

        user = json.loads(data["user"])
        if not isinstance(user, dict) or not isinstance(user.get("id"), int):
            return None
        return user
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def message_metadata(message):
    """Get a displayable message type, text/caption, and Telegram file ID."""
    if message.get("text") is not None:
        return "text", message["text"], None

    content_types = (
        "photo", "video", "document", "audio", "voice", "video_note",
        "sticker", "animation", "location", "contact", "poll", "venue",
    )
    for content_type in content_types:
        content = message.get(content_type)
        if content is None:
            continue
        if content_type == "photo" and content:
            content = content[-1]
        file_id = content.get("file_id") if isinstance(content, dict) else None
        return content_type, message.get("caption") or "", file_id
    return "unknown", message.get("caption") or "", None


def show_teacher_menu(chat_id):
    send(
        chat_id,
        "O'quvchi bilan yozishish uchun tugmani bosing.\n"
        "Kelgan xabarga Reply qilib javob berish ham mumkin.",
        reply_markup={
            "inline_keyboard": [[{
                "text": "✉️ O'quvchiga yozish",
                "callback_data": "students:0",
            }]]
        },
    )


def show_student_picker(chat_id, page=0, message_id=None):
    page = max(0, page)
    conn = get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
        rows = conn.execute(
            """SELECT user_id, full_name, group_name FROM students
               ORDER BY full_name COLLATE NOCASE, user_id LIMIT ? OFFSET ?""",
            (STUDENT_PAGE_SIZE, page * STUDENT_PAGE_SIZE),
        ).fetchall()
    finally:
        conn.close()

    if not total:
        text = "Hozircha o'quvchilar ro'yxati bo'sh."
        markup = {"inline_keyboard": [[{
            "text": "⬅️ Menyu",
            "callback_data": "teacher:menu",
        }]]}
    else:
        start = page * STUDENT_PAGE_SIZE + 1
        end = start + len(rows) - 1
        text = f"Yozmoqchi bo'lgan o'quvchini tanlang ({start}–{end} / {total}):"
        keyboard = []
        for row in rows:
            label = row["full_name"] or str(row["user_id"])
            if row["group_name"]:
                label += f" · {row['group_name']}"
            keyboard.append([{
                "text": label[:60],
                "callback_data": f"student:{row['user_id']}",
            }])
        navigation = []
        if page > 0:
            navigation.append({"text": "⬅️ Oldingi", "callback_data": f"students:{page - 1}"})
        if (page + 1) * STUDENT_PAGE_SIZE < total:
            navigation.append({"text": "Keyingi ➡️", "callback_data": f"students:{page + 1}"})
        if navigation:
            keyboard.append(navigation)
        keyboard.append([{"text": "✖️ Bekor qilish", "callback_data": "teacher:menu"}])
        markup = {"inline_keyboard": keyboard}

    if message_id:
        return tg(
            "editMessageText", chat_id=chat_id, message_id=message_id,
            text=text, reply_markup=markup,
        )
    return send(chat_id, text, reply_markup=markup)


def handle_callback_query(callback):
    callback_id = callback.get("id")
    sender = callback.get("from", {})
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    if (
        sender.get("id") != TEACHER_ID
        or chat.get("type") != "private"
        or chat.get("id") != TEACHER_ID
    ):
        tg("answerCallbackQuery", callback_query_id=callback_id, text="Ruxsat yo'q.", show_alert=True)
        return

    data = callback.get("data", "")
    chat_id = chat["id"]
    message_id = message.get("message_id")

    if data.startswith("students:"):
        try:
            page = int(data.partition(":")[2])
        except ValueError:
            tg("answerCallbackQuery", callback_query_id=callback_id, text="Noto'g'ri sahifa.")
            return
        tg("answerCallbackQuery", callback_query_id=callback_id)
        show_student_picker(chat_id, page, message_id)
        return

    if data.startswith("student:"):
        try:
            student_id = int(data.partition(":")[2])
        except ValueError:
            student_id = 0
        conn = get_conn()
        try:
            student = conn.execute(
                "SELECT full_name FROM students WHERE user_id = ?", (student_id,)
            ).fetchone()
        finally:
            conn.close()
        if not student:
            tg("answerCallbackQuery", callback_query_id=callback_id, text="O'quvchi topilmadi.", show_alert=True)
            return
        PENDING_TEACHER_MESSAGE[TEACHER_ID] = student_id
        tg("answerCallbackQuery", callback_query_id=callback_id, text="O'quvchi tanlandi.")
        send(
            chat_id,
            f"{student['full_name']} ga yuboriladigan xabarni yozing yoki media yuboring.\n"
            "Bekor qilish uchun /cancel yuboring.",
        )
        return

    if data == "teacher:menu":
        tg("answerCallbackQuery", callback_query_id=callback_id)
        PENDING_TEACHER_MESSAGE.pop(TEACHER_ID, None)
        show_teacher_menu(chat_id)
        return

    tg("answerCallbackQuery", callback_query_id=callback_id, text="Tugma eskirgan.")


# ══════════════════════════════════════════
#  BOT LOGIC
# ══════════════════════════════════════════

def forward_to_teacher(conn, student_id, message_id, content_type, text, file_id):
    result = tg("forwardMessage",
                chat_id=TEACHER_ID,
                from_chat_id=student_id,
                message_id=message_id)
    forwarded_id = result.get("message_id")
    if forwarded_id:
        conn.execute("""
            INSERT INTO messages
                (student_id, forwarded_message_id, direction, content_type, text, file_id)
            VALUES (?, ?, 'in', ?, ?, ?)
        """, (student_id, forwarded_id, content_type, text, file_id))
        conn.commit()
    return forwarded_id


def handle_update(update):
    callback = update.get("callback_query")
    if callback:
        try:
            handle_callback_query(callback)
        except Exception as e:
            log.error("Tugma so'rovida xato: %s", e)
            if callback.get("id"):
                tg("answerCallbackQuery", callback_query_id=callback["id"], text="Xatolik yuz berdi.")
        return

    msg = update.get("message")
    if not msg:
        return

    from_id = msg["from"]["id"]
    msg_id  = msg["message_id"]
    content_type, text, file_id = message_metadata(msg)

    if msg["chat"]["type"] != "private":
        return

    conn = get_conn()
    try:

        # ── O'QITUVCHI ──
        if from_id == TEACHER_ID:
            command = text.split(maxsplit=1)[0].split("@", 1)[0] if text else ""
            if command == "/start":
                PENDING_TEACHER_MESSAGE.pop(TEACHER_ID, None)
                show_teacher_menu(TEACHER_ID)
                return

            if command == "/cancel":
                PENDING_TEACHER_MESSAGE.pop(TEACHER_ID, None)
                send(TEACHER_ID, "Yozish bekor qilindi.")
                return

            target_student_id = PENDING_TEACHER_MESSAGE.get(TEACHER_ID)
            if target_student_id:
                result = tg(
                    "copyMessage", chat_id=target_student_id,
                    from_chat_id=TEACHER_ID, message_id=msg_id,
                )
                if result.get("message_id"):
                    conn.execute("""
                        INSERT INTO messages
                            (student_id, teacher_message_id, direction, content_type, text, file_id)
                        VALUES (?, ?, 'out', ?, ?, ?)
                    """, (target_student_id, msg_id, content_type, text, file_id))
                    conn.commit()
                    PENDING_TEACHER_MESSAGE.pop(TEACHER_ID, None)
                    student = conn.execute(
                        "SELECT full_name FROM students WHERE user_id = ?",
                        (target_student_id,),
                    ).fetchone()
                    name = student["full_name"] if student else str(target_student_id)
                    send(TEACHER_ID, f"✅ {name} ga xabar yuborildi.")
                else:
                    send(
                        TEACHER_ID,
                        "❌ Xabar yuborilmadi. Qayta urinib ko'ring yoki /cancel yuboring.",
                    )
                return

            reply = msg.get("reply_to_message")

            if not reply:
                show_teacher_menu(TEACHER_ID)
                return

            row = conn.execute("""
                SELECT student_id FROM messages
                WHERE forwarded_message_id = ?
            """, (reply["message_id"],)).fetchone()

            if not row:
                send(TEACHER_ID, "❌ Bu xabar qaysi o'quvchiga tegishli aniqlanmadi.")
                return

            student_id = row["student_id"]
            result = tg("copyMessage",
                        chat_id=student_id,
                        from_chat_id=TEACHER_ID,
                        message_id=msg_id)

            if result.get("message_id"):
                conn.execute("""
                    INSERT INTO messages
                        (student_id, teacher_message_id, direction, content_type, text, file_id)
                    VALUES (?, ?, 'out', ?, ?, ?)
                """, (student_id, msg_id, content_type, text, file_id))
                conn.commit()

                student = conn.execute(
                    "SELECT full_name FROM students WHERE user_id = ?", (student_id,)
                ).fetchone()
                name = student["full_name"] if student else str(student_id)
                send(TEACHER_ID, f"✅ {name} ga yuborildi.")
            else:
                send(TEACHER_ID, "❌ Javobni o'quvchiga yuborib bo'lmadi.")
            return

        # ── O'QUVCHI ──
        if text.startswith("/start") and (
            text == "/start" or text.startswith("/start ")
            or text.startswith("/start@")
        ):
            user      = msg["from"]
            full_name = f"{user.get('first_name','')}{' '+user.get('last_name','') if user.get('last_name') else ''}".strip()
            conn.execute("""
                INSERT INTO students (user_id, full_name)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET full_name = excluded.full_name
            """, (from_id, full_name))
            conn.commit()
            send(from_id,
                 f"👋 Salom, {full_name}!\n\n"
                 "Bu bot orqali o'qituvchingizga ish yoki vazifa yuboring.\n"
                 "Fayl, rasm yoki xabar — hammasi o'qituvchiga boradi.")
            return

        student = conn.execute(
            "SELECT * FROM students WHERE user_id = ?", (from_id,)
        ).fetchone()
        if not student:
            send(from_id, "Avval /start bosing.")
            return

        forwarded_id = forward_to_teacher(
            conn, from_id, msg_id, content_type, text, file_id
        )
        if forwarded_id:
            send(from_id, "✅ Xabaringiz o'qituvchiga yuborildi. Javob kutib turing.")
        else:
            send(from_id, "❌ Xabar yuborilmadi. Birozdan keyin qayta urinib ko'ring.")

    finally:
        conn.close()


def run_polling():
    log.info("Bot polling boshlandi...")
    offset = 0
    while True:
        try:
            updates = tg("getUpdates", offset=offset, timeout=30,
                         request_timeout=35,
                         allowed_updates=["message", "callback_query"])
            if isinstance(updates, list):
                for upd in updates:
                    offset = upd["update_id"] + 1
                    try:
                        handle_update(upd)
                    except Exception as e:
                        log.error("Update xatosi: %s", e)
            else:
                # Avoid a tight loop after Telegram returns an API error (e.g. webhook/409).
                time.sleep(5)
        except Exception as e:
            log.error("Polling xatosi: %s", e)
            time.sleep(5)


# ══════════════════════════════════════════
#  FLASK (MINI APP API)
# ══════════════════════════════════════════

app = Flask(__name__, static_folder=None)


def auth_ok():
    authorization = request.headers.get("Authorization", "")
    scheme, _, init_data = authorization.partition(" ")
    if scheme.lower() != "tma":
        return False
    user = validate_telegram_init_data(init_data)
    return bool(user and user.get("id") == TEACHER_ID)


@app.route("/")
def index():
    return send_from_directory(APP_DIR, "index.html")


@app.route("/api/students")
def api_students():
    if not auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_conn()
    rows = conn.execute("""
        SELECT s.user_id, s.full_name, s.group_name, s.registered_at,
               COUNT(m.id)                                          AS total_messages,
               COALESCE(SUM(CASE WHEN m.direction='in' AND m.read_at IS NULL
                                 THEN 1 ELSE 0 END), 0)            AS unread
        FROM students s
        LEFT JOIN messages m ON s.user_id = m.student_id
        GROUP BY s.user_id
        ORDER BY s.registered_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/messages/<int:student_id>")
def api_messages(student_id):
    if not auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_conn()
    conn.execute("""
        UPDATE messages SET read_at = CURRENT_TIMESTAMP
        WHERE student_id = ? AND direction = 'in' AND read_at IS NULL
    """, (student_id,))
    conn.commit()
    rows = conn.execute("""
        SELECT id, direction, content_type, text, file_id,
               forwarded_message_id, sent_at
        FROM messages WHERE student_id = ?
        ORDER BY sent_at ASC
    """, (student_id,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/send", methods=["POST"])
def api_send():
    if not auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON obyekt yuborilishi kerak"}), 400
    student_id = data.get("student_id")
    text = data.get("text")
    if not isinstance(student_id, int) or isinstance(student_id, bool) or student_id <= 0:
        return jsonify({"error": "student_id musbat butun son bo'lishi kerak"}), 400
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        return jsonify({"error": "Matn 1–4000 belgi bo'lishi kerak"}), 400
    text = text.strip()

    conn    = get_conn()
    student = conn.execute(
        "SELECT * FROM students WHERE user_id = ?", (student_id,)
    ).fetchone()
    if not student:
        conn.close()
        return jsonify({"error": "O'quvchi topilmadi"}), 404

    result = tg("sendMessage", chat_id=student_id,
                text=f"👩‍🏫 O'qituvchi:\n\n{text}")
    if result.get("message_id"):
        conn.execute("""
            INSERT INTO messages (student_id, direction, content_type, text)
            VALUES (?, 'out', 'text', ?)
        """, (student_id, text))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    conn.close()
    return jsonify({"error": "Telegram xatosi"}), 500


@app.route("/api/student/update", methods=["POST"])
def api_student_update():
    if not auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON obyekt yuborilishi kerak"}), 400
    user_id = data.get("user_id")
    group_name = data.get("group_name", "")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        return jsonify({"error": "user_id musbat butun son bo'lishi kerak"}), 400
    if not isinstance(group_name, str) or len(group_name) > 100:
        return jsonify({"error": "group_name 100 belgidan oshmasligi kerak"}), 400
    conn = get_conn()
    conn.execute("UPDATE students SET group_name=? WHERE user_id=?",
                 (group_name.strip(), user_id))
    if conn.execute("SELECT changes()").fetchone()[0] == 0:
        conn.close()
        return jsonify({"error": "O'quvchi topilmadi"}), 404
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════
#  START
# ══════════════════════════════════════════

if __name__ == "__main__":
    init_db()

    # Bot ni alohida threadda ishlatamiz
    t = threading.Thread(target=run_polling, daemon=True)
    t.start()

    # Flask asosiy threadda ishlaydi
    port = int(os.getenv("PORT", 5000))
    log.info("Mini App server port %d da ishga tushdi", port)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
