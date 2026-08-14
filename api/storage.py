"""
لایه ذخیره‌سازی برای TodoBot
--------------------------------
چرا Redis (Upstash) و نه فایل یا SQLite؟
در محیط سرورلس (Vercel / AWS Lambda / Cloudflare Workers) دیسک هر اجرا موقتی است؛
هر بار که تابع فراخوانی می‌شود ممکن است روی یک ماشین کاملاً جدید اجرا شود.
پس فایل JSON یا SQLite محلی، داده را بین درخواست‌ها گم می‌کند.
Upstash Redis یک دیتابیس Redis بدون‌سرور با REST API است (بدون نیاز به کانکشن دائمی)
که دقیقاً برای همین معماری ساخته شده و پلن رایگان دارد: https://upstash.com

اگر می‌خواهی از چیز دیگری استفاده کنی (Vercel KV, Supabase, DynamoDB, Firebase)،
فقط کافی‌ست همین کلاس Storage را با همان متدها بازنویسی کنی؛ بقیه‌ی کد دست‌نخورده می‌ماند.
"""

import os
import json
import time
import urllib.request
import urllib.error
import urllib.parse

UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")


class StorageError(Exception):
    pass


def _redis_command(*parts):
    """اجرای یک دستور Redis از طریق REST API آپستش."""
    if not UPSTASH_URL or not UPSTASH_TOKEN:
        raise StorageError(
            "متغیرهای محیطی UPSTASH_REDIS_REST_URL و UPSTASH_REDIS_REST_TOKEN تنظیم نشده‌اند."
        )
    url = UPSTASH_URL.rstrip("/") + "/" + "/".join(str(p) for p in parts)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("result")
    except urllib.error.HTTPError as e:
        raise StorageError(f"خطای Redis: {e.read().decode('utf-8')}")


def _key(user_id: int) -> str:
    return f"todobot:tasks:{user_id}"


def get_tasks(user_id: int) -> list:
    """لیست کارهای کاربر را برمی‌گرداند. هر کار: {id, text, done, created_at}"""
    raw = _redis_command("get", _key(user_id))
    if not raw:
        return []
    return json.loads(urllib.parse.unquote(raw))


def _save_tasks(user_id: int, tasks: list) -> None:
    payload = json.dumps(tasks, ensure_ascii=False)
    # از GET/SET ساده استفاده می‌کنیم؛ برای مقیاس بالا بهتر است از تراکنش/قفل استفاده شود.
    encoded = urllib.parse.quote(payload)
    _redis_command("set", _key(user_id), encoded)


def add_task(user_id: int, text: str) -> dict:
    tasks = get_tasks(user_id)
    new_id = (max([t["id"] for t in tasks], default=0)) + 1
    task = {
        "id": new_id,
        "text": text.strip(),
        "done": False,
        "created_at": int(time.time()),
    }
    tasks.append(task)
    _save_tasks(user_id, tasks)
    return task


def delete_task(user_id: int, task_id: int) -> bool:
    tasks = get_tasks(user_id)
    new_tasks = [t for t in tasks if t["id"] != task_id]
    if len(new_tasks) == len(tasks):
        return False
    _save_tasks(user_id, new_tasks)
    return True


def mark_done(user_id: int, task_id: int) -> bool:
    tasks = get_tasks(user_id)
    for t in tasks:
        if t["id"] == task_id:
            t["done"] = True
            _save_tasks(user_id, tasks)
            return True
    return False


def clear_all(user_id: int) -> None:
    _redis_command("del", _key(user_id))
