"""
Сервер личного мессенджера для BotHost.
Запуск: python main.py

Переменные окружения (задаются в панели BotHost):
  PORT       - порт, который слушает веб-сервер (BotHost подставит сам, по умолчанию 3000)
  SECRET_KEY - секретный ключ для API (заголовок X-Secret-Key)
  BOT_TOKEN  - токен Telegram-бота (админка). Если не задан - бот просто не запустится.
  DB_PATH    - путь к файлу SQLite (по умолчанию messenger.db)
"""

import asyncio
import os
import sqlite3
import threading
import time

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

# ----------------------------- Конфигурация -----------------------------

PORT = int(os.getenv("PORT", 3000))
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
BOT_TOKEN = os.getenv("BOT_TOKEN")  # None -> бот выключен
DB_PATH = os.getenv("DB_PATH", "messenger.db")

LONG_POLL_TIMEOUT = 30      # секунд удержания соединения в /api/get
MAX_MESSAGES_PER_REQUEST = 200

# ----------------------------- База данных ------------------------------

_db_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.execute(
    """
    CREATE TABLE IF NOT EXISTS messages (
        id     INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT    NOT NULL,
        text   TEXT    NOT NULL,
        ts     REAL    NOT NULL
    )
    """
)
_conn.commit()


def db_add(sender: str, text: str) -> int:
    with _db_lock:
        cur = _conn.execute(
            "INSERT INTO messages (sender, text, ts) VALUES (?, ?, ?)",
            (sender, text, time.time()),
        )
        _conn.commit()
        return cur.lastrowid


def db_get_after(last_id: int) -> list[dict]:
    with _db_lock:
        cur = _conn.execute(
            "SELECT id, sender, text, ts FROM messages "
            "WHERE id > ? ORDER BY id ASC LIMIT ?",
            (last_id, MAX_MESSAGES_PER_REQUEST),
        )
        return [
            {"id": row[0], "sender": row[1], "text": row[2], "ts": row[3]}
            for row in cur.fetchall()
        ]


def db_count() -> int:
    with _db_lock:
        return _conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


# Сигнал "появилось новое сообщение" - будит все ожидающие long-poll запросы
new_message_event = asyncio.Event()

# ----------------------------- HTTP API ---------------------------------


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Проверка X-Secret-Key для всех /api/* эндпоинтов."""
    if request.path.startswith("/api/"):
        if request.headers.get("X-Secret-Key") != SECRET_KEY:
            return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def api_send(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    sender = str(data.get("sender", "")).strip()
    text = str(data.get("text", ""))
    if not sender or not text.strip():
        return web.json_response({"error": "sender and text are required"}, status=400)

    msg_id = await asyncio.to_thread(db_add, sender, text)
    new_message_event.set()  # мгновенно будим long polling клиентов
    return web.json_response({"ok": True, "id": msg_id})


async def api_get(request: web.Request) -> web.Response:
    """Long polling: держим соединение до LONG_POLL_TIMEOUT сек,
    если новых сообщений нет."""
    try:
        last_id = int(request.query.get("last_id", "0"))
    except ValueError:
        last_id = 0

    deadline = time.monotonic() + LONG_POLL_TIMEOUT

    while True:
        # clear() ДО проверки - иначе можно пропустить событие,
        # пришедшее между проверкой БД и очисткой флага
        new_message_event.clear()
        messages = await asyncio.to_thread(db_get_after, last_id)
        if messages:
            return web.json_response({"messages": messages})

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return web.json_response({"messages": []})

        try:
            await asyncio.wait_for(new_message_event.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            pass


# ----------------------------- Telegram-бот (админка) -------------------


async def cmd_status(message: Message) -> None:
    count = await asyncio.to_thread(db_count)
    await message.answer(
        "\u2705 Сервер жив.\n"
        f"\U0001f4e8 Сообщений в базе: {count}\n"
        f"\U0001f310 Порт: {PORT}"
    )


async def start_bot() -> None:
    if not BOT_TOKEN:
        print("[bot] BOT_TOKEN не задан - бот отключён.")
        return
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.message.register(cmd_status, Command("status"))
    print("[bot] Бот запущен, команда /status доступна.")
    await dp.start_polling(bot)


# ----------------------------- Запуск -----------------------------------


async def main() -> None:
    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/health", health)
    app.router.add_post("/api/send", api_send)
    app.router.add_get("/api/get", api_get)

    runner = web.AppRunner(app)
    await runner.setup()
    # ОБЯЗАТЕЛЬНО 0.0.0.0 и порт из PORT - иначе reverse proxy BotHost не достучится
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    print(f"[server] Слушаю http://0.0.0.0:{PORT}")

    await start_bot()  # блокируется (polling); без токена возвращается сразу
    # Если бота нет - просто живём вечно
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())