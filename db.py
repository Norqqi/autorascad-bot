"""Хранение подписчиков в SQLite (асинхронно, через aiosqlite).

На хостинге (Bothost) файл кладётся в DATA_DIR (/app/data), иначе данные
стираются при перезапуске контейнера.
"""

import os

import aiosqlite

DB_PATH = os.path.join(os.getenv("DATA_DIR", ""), "subscribers.db") if os.getenv("DATA_DIR") else "subscribers.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    chat_id INTEGER PRIMARY KEY,
    username TEXT,
    subscribed INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def init() -> None:
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_SCHEMA)
        await db.commit()


async def subscribe(chat_id: int, username: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO subscribers (chat_id, username, subscribed)
            VALUES (?, ?, 1)
            ON CONFLICT(chat_id) DO UPDATE SET subscribed = 1, username = excluded.username
            """,
            (chat_id, username),
        )
        await db.commit()


async def ensure_subscribed(chat_id: int, username: str | None) -> bool:
    """Автоподписка: пишем в базу только если человек ещё не активный.

    Возвращает True, если подписка была оформлена прямо сейчас.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT subscribed FROM subscribers WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        if row is not None and row[0] == 1:
            return False
        await db.execute(
            """
            INSERT INTO subscribers (chat_id, username, subscribed)
            VALUES (?, ?, 1)
            ON CONFLICT(chat_id) DO UPDATE SET subscribed = 1, username = excluded.username
            """,
            (chat_id, username),
        )
        await db.commit()
    return True


async def unsubscribe(chat_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE subscribers SET subscribed = 0 WHERE chat_id = ?", (chat_id,)
        )
        await db.commit()


async def get_active() -> list[int]:
    """Все chat_id с активной подпиской."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT chat_id FROM subscribers WHERE subscribed = 1"
        )
        rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def count() -> tuple[int, int]:
    """(всего подписчиков, активных)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*), COALESCE(SUM(subscribed), 0) FROM subscribers"
        )
        total, active = await cursor.fetchone()
    return total, active