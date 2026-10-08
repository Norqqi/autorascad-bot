"""Планировщик: ежедневные уведомления в заданное время"""

import asyncio
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import config
import db

CHECK_INTERVAL = 30  # секунд между проверками


async def broadcast(bot: Bot, text: str) -> tuple[int, int]:
    """Отправляет сообщение всем подписчикам. Возвращает (успешно, ошибок)."""
    ok = failed = 0
    for chat_id in await db.get_active():
        try:
            await bot.send_message(chat_id, text)
            ok += 1
        except TelegramAPIError as e:
            # пользователь заблокировал бота или сообщение нельзя доставить
            failed += 1
            print(f"[broadcast] не доставлено {chat_id}: {e.__class__.__name__}")
        await asyncio.sleep(0.05)  # защита от флуд-лимитов Telegram
    return ok, failed


async def _run(bot: Bot) -> None:
    fired: set[tuple[str, str]] = set()  # (дата, время) — уже отправлено

    while True:
        now = datetime.now()
        key_date = now.strftime("%Y-%m-%d")

        for t in config.NOTIFY_TIMES:
            hhmm = t.strftime("%H:%M")
            # срабатываем, если текущая минута совпала и сегодня ещё не отправляли
            if (now.hour, now.minute) == (t.hour, t.minute) and (key_date, hhmm) not in fired:
                fired.add((key_date, hhmm))
                ok, failed = await broadcast(
                    bot, f"⏰ Напоминание: сейчас {hhmm}!"
                )
                print(f"[scheduler] {hhmm}: доставлено {ok}, ошибок {failed}")

        # чистим старые записи, чтобы множество не росло бесконечно
        fired = {k for k in fired if k[0] == key_date}

        await asyncio.sleep(CHECK_INTERVAL)


def start(bot: Bot) -> asyncio.Task:
    return asyncio.create_task(_run(bot), name="scheduler")
