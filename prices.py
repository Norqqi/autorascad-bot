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


def to_float(raw) -> float | None:
    """«150», «150 ₽», «1 500», «1,38», «1.38» -> 150 / 1500 / 1.38. None = мусор."""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text or "-" in text:      # «-5» или диапазон «100-150» — не цена
        return None

    found = re.search(r"\d[\d\s.,]*\d|\d", text)
    if not found:
        return None
    core = found.group(0)

    sep = max(core.rfind("."), core.rfind(","))   # последний разделитель — дробная часть
    if sep < 0:
        digits = re.sub(r"\D", "", core)
        if not digits or len(digits) > 7:
            return None
        return _ok(float(digits))

    whole = re.sub(r"\D", "", core[:sep])
    frac = re.sub(r"\D", "", core[sep + 1:])
    if not frac or len(frac) > 2:
        # «150», «150.» или разделители разрядов: «1,500», «1 500,000»
        digits = re.sub(r"\D", "", core)
        if len(digits) > 7:
            return None
        return _ok(float(digits or 0))
    return _ok(float(f"{whole or 0}.{frac}"))


def _ok(value: float) -> float | None:
    """Потолок 10 млн — чтобы мусор не превращался в «цену»."""
    if not (0 < value <= 10_000_000):
        return None
    return round(value, 2)


def to_int(raw) -> int | None:
    """Совместимость: только целые значения."""
    value = to_float(raw)
    return int(value) if value is not None and value.is_integer() else None


def fmt(value) -> str:
    """150 -> «150», 1.38 -> «1,38», 1500.5 -> «1 500,5» (для показа человеку)."""
    try:
        number = round(float(value), 2)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    whole, _, frac = text.partition(".")
    whole = f"{int(whole or 0):,}".replace(",", " ")
    return f"{whole},{frac}" if frac else whole


def parse(raw: str) -> str | None:
    """Что прислал админ -> нормализованная цена («150 ₽», «1,38 ₽»). None = мусор."""
    value = to_float(raw)
    if not value:
        return None
    return fmt(value) + " ₽"


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
