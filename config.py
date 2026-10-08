"""Конфигурация бота: читает переменные из .env или окружения хостинга."""

import os
from datetime import time

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))

# Если провайдер блокирует api.telegram.org — можно указать рабочий IP.
# На хостинге (Bothost) эта переменная НЕ задаётся — используется обычный DNS.
TELEGRAM_API_IP: str = os.getenv("TELEGRAM_API_IP", "")

# Username продавца для кнопки «Купить» (без @).
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "")

# Порт веб-сервера мини-приложения.
# На Bothost приходит из окружения (PORT), локально — 8080.
PORT: int = int(os.getenv("PORT", "8080"))

# Постоянное хранилище на хостинге (иначе данные стираются при рестарте).
DATA_DIR: str = os.getenv("DATA_DIR", "")

# URL мини-приложения (HTTPS). Если WEBAPP_URL не задан — выводится из DOMAIN.
_WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
_DOMAIN = os.getenv("DOMAIN", "").strip()
WEBAPP_URL: str = _WEBAPP_URL or (f"https://{_DOMAIN}" if _DOMAIN else "")


def _parse_times(raw: str) -> list[time]:
    """'09:00,18:00' -> [time(9, 0), time(18, 0)]"""
    times: list[time] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h, m = part.split(":")
            times.append(time(int(h), int(m)))
        except ValueError:
            print(f"[config] Неверное время уведомления: {part!r} — пропускаю")
    return times


NOTIFY_TIMES: list[time] = _parse_times(os.getenv("NOTIFY_TIMES", "09:00"))

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN не задан! Укажи его в .env или в настройках хостинга.")
