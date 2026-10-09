"""Цены товаров: переопределение поверх store.PRODUCTS.

По умолчанию цена берётся из кода (store.py). Как только админ поменял
цену через бота — значение ложится сюда и перекрывает дефолт.

Файл рядом с базой (DATA_DIR на хостинге — /app/data), переживает рестарты.
Мини-приложение отдаёт HTML заново на каждый запрос, поэтому новая цена
появляется в каталоге сразу, redeploy не нужен.
"""

import json
import os
import re

_DATA_DIR = os.getenv("DATA_DIR", "")
PRICES_FILE = os.path.join(_DATA_DIR, "prices.json") if _DATA_DIR else "prices.json"

# «150», «150 ₽», «150р», «150 руб.», «1 500» -> «150 ₽»


def load_all() -> dict[int, str]:
    """{id товара: цена строкой}. Пусто = цены не менялись."""
    try:
        with open(PRICES_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        return {int(k): str(v).strip() for k, v in raw.items() if str(v).strip()}
    except (OSError, ValueError, TypeError):
        return {}


def save_all(data: dict[int, str]) -> None:
    folder = os.path.dirname(PRICES_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(PRICES_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in data.items()}, f, ensure_ascii=False, indent=2)


def parse(raw: str) -> str | None:
    """Что прислал админ -> нормализованная цена («150 ₽»). None = мусор."""
    if not raw:
        return None
    text = str(raw).strip()
    if "-" in text:          # «-5» или диапазон «100-150» — не цена
        return None
    # чистим всё, кроме цифр: пробелы, ₽, «руб.», «р.», «rub»
    digits = re.sub(r"\D", "", text.replace("\u00a0", " "))
    if not digits or len(digits) > 7:
        return None
    value = int(digits)
    if value <= 0:
        return None
    return f"{value:,}".replace(",", " ") + " ₽"


def get_price(product_id: int, default: str) -> str:
    return load_all().get(product_id, default)


def set_price(product_id: int, price: str) -> None:
    data = load_all()
    data[product_id] = price
    save_all(data)


def reset(product_id: int) -> bool:
    """Вернуть дефолтную цену из кода. True — если что-то сбросили."""
    data = load_all()
    existed = data.pop(product_id, None) is not None
    if existed:
        save_all(data)
    return existed
