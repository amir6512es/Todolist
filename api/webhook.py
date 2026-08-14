"""
TodoBot — هندلر وبهوک تلگرام (سازگار با Vercel Serverless Functions - Python)
--------------------------------------------------------------------------
هر پیام/کلیک روی دکمه از تلگرام به این آدرس POST می‌شود، پردازش می‌شود
و تابع بلافاصله برمی‌گردد — بدون حلقه polling، بدون سرور دائمی روشن.

استقرار: این فایل باید داخل پوشه‌ی api/ در ریشه‌ی پروژه باشد (استاندارد Vercel).
آدرس نهایی می‌شود: https://<your-project>.vercel.app/api/webhook
"""

import os
import json
import urllib.request

import storage

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _call_telegram(method: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_URL}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_message(chat_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _call_telegram("sendMessage", payload)


def answer_callback(callback_query_id: str, text: str = ""):
    return _call_telegram(
        "answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text}
    )


def edit_message(chat_id: int, message_id: int, text: str, reply_markup: dict = None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        return _call_telegram("editMessageText", payload)
    except Exception:
        pass  # پیام تغییری نکرده یا خیلی قدیمی شده — بی‌خطر است، نادیده می‌گیریم


# ---------------------------------------------------------------------
# ساخت متن و کیبورد لیست کارها
# ---------------------------------------------------------------------

def render_task_list(user_id: int):
    tasks = storage.get_tasks(user_id)
    if not tasks:
        return "📭 هیچ کاری ثبت نکرده‌ای.\nبرای افزودن، فقط متن کار رو بفرست.", None

    lines = ["📋 <b>لیست کارهای تو:</b>\n"]
    keyboard = []
    for t in tasks:
        mark = "✅" if t["done"] else "◻️"
        lines.append(f"{mark} {t['id']}. {t['text']}")
        row = []
        if not t["done"]:
            row.append({"text": f"✅ انجام شد ({t['id']})", "callback_data": f"done:{t['id']}"})
        row.append({"text": f"🗑 حذف ({t['id']})", "callback_data": f"del:{t['id']}"})
        keyboard.append(row)

    text = "\n".join(lines)
    return text, {"inline_keyboard": keyboard}


# ---------------------------------------------------------------------
# مدیریت دستورات و پیام‌ها
# ---------------------------------------------------------------------

HELP_TEXT = (
    "👋 به <b>TodoBot</b> خوش اومدی!\n\n"
    "دستورات:\n"
    "• هر متنی بفرستی = یک کار جدید ثبت می‌شه\n"
    "/list — نمایش لیست کارها\n"
    "/clear — حذف همه‌ی کارها\n"
    "/help — راهنما"
)


def handle_message(message: dict):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = (message.get("text") or "").strip()

    if text in ("/start", "/help"):
        send_message(chat_id, HELP_TEXT)
        return

    if text == "/list":
        body, kb = render_task_list(user_id)
        send_message(chat_id, body, kb)
        return

    if text == "/clear":
        storage.clear_all(user_id)
        send_message(chat_id, "🧹 همه‌ی کارها حذف شدن.")
        return

    if not text:
        send_message(chat_id, "فقط متن پیام رو به عنوان کار می‌تونم ثبت کنم.")
        return

    # هر پیام معمولی = ثبت کار جدید
    task = storage.add_task(user_id, text)
    send_message(chat_id, f"✅ کار ثبت شد: «{task['text']}» (شماره {task['id']})")


def handle_callback(callback_query: dict):
    data = callback_query["data"]
    message = callback_query["message"]
    chat_id = message["chat"]["id"]
    message_id = message["message_id"]
    user_id = callback_query["from"]["id"]

    action, _, raw_id = data.partition(":")
    try:
        task_id = int(raw_id)
    except ValueError:
        answer_callback(callback_query["id"], "شناسه نامعتبر")
        return

    if action == "done":
        ok = storage.mark_done(user_id, task_id)
        answer_callback(callback_query["id"], "انجام شد ✅" if ok else "پیدا نشد")
    elif action == "del":
        ok = storage.delete_task(user_id, task_id)
        answer_callback(callback_query["id"], "حذف شد 🗑" if ok else "پیدا نشد")
    else:
        answer_callback(callback_query["id"])
        return

    body, kb = render_task_list(user_id)
    edit_message(chat_id, message_id, body, kb)


# ---------------------------------------------------------------------
# ورودی سرورلس (Vercel Python runtime: کلاس handler به سبک BaseHTTPRequestHandler)
# ---------------------------------------------------------------------

from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)
            update = json.loads(raw_body.decode("utf-8"))

            if "message" in update and "text" in update.get("message", {}):
                handle_message(update["message"])
            elif "callback_query" in update:
                handle_callback(update["callback_query"])
            # سایر انواع آپدیت (عکس، استیکر و ...) فعلاً نادیده گرفته می‌شوند

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        except Exception as e:
            # همیشه 200 برمی‌گردونیم تا تلگرام دوباره‌ارسالی بی‌پایان نداشته باشه؛
            # خطا رو فقط لاگ می‌کنیم (در Vercel در بخش Logs قابل مشاهده است)
            print("webhook error:", repr(e))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"TodoBot webhook is alive.")
