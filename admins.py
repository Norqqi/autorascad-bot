"""Дополнительные админы бота.

Главный админ всегда задаётся переменной окружения ADMIN_ID — его
нельзя удалить. Сюда складываются остальные, добавленные командой
/add @username или кнопками в админ-панели.

Файл лежит рядом с базой (DATA_DIR на хостинге), переживает рестарты.
"""

import json
import os

_DATA_DIR = os.getenv("DATA_DIR", "")
ADMINS_FILE = os.path.join(_DATA_DIR, "admins.json") if _DATA_DIR else "admins.json"


def load() -> dict[int, str]:
    """{user_id: username без @}"""
    try:
        with open(ADMINS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        return {int(k): str(v) for k, v in raw.items()}
    except (OSError, ValueError, TypeError):
        return {}


def save(data: dict[int, str]) -> None:
    folder = os.path.dirname(ADMINS_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in data.items()}, f, ensure_ascii=False, indent=2)


def add(user_id: int, username: str = "") -> None:
    data = load()
    data[user_id] = username.lstrip("@")
    save(data)


def remove(user_id: int) -> bool:
    data = load()
    existed = data.pop(user_id, None) is not None
    if existed:
        save(data)
    return existed


def is_admin(user_id: int, main_admin_id: int) -> bool:
    """Главный админ + все добавленные."""
    if main_admin_id and user_id == main_admin_id:
        return True
    return user_id in load()


def display_name(user_id: int, username: str = "") -> str:
    return f"@{username.lstrip('@')}" if username else f"id {user_id}"
