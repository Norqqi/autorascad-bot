"""Наличие товаров на складе.

Хранится в JSON-файле рядом с базой (DATA_DIR на хостинге — /app/data),
чтобы переживать перезапуски контейнера. Админ меняет через /stock,
мини-приложение читает при каждой отрисовке — redeploy не нужен.
"""

import json
import os

_DATA_DIR = os.getenv("DATA_DIR", "")
STOCK_FILE = os.path.join(_DATA_DIR, "stock.json") if _DATA_DIR else "stock.json"


def load_all() -> dict[int, bool]:
    """{id товара: в наличии ли}. Отсутствующая запись = в наличии."""
    try:
        with open(STOCK_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        return {int(k): bool(v) for k, v in raw.items()}
    except (OSError, ValueError, TypeError):
        return {}


def save_all(data: dict[int, bool]) -> None:
    folder = os.path.dirname(STOCK_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(STOCK_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): bool(v) for k, v in data.items()}, f, ensure_ascii=False, indent=2)


def is_available(product_id: int) -> bool:
    return load_all().get(product_id, True)


def set_available(product_id: int, available: bool) -> None:
    data = load_all()
    data[product_id] = available
    save_all(data)


def toggle(product_id: int) -> bool:
    """Переключает наличие. Возвращает новое состояние."""
    new_state = not is_available(product_id)
    set_available(product_id, new_state)
    return new_state
