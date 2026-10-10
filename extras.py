"""Настройки витрины, которые админ меняет прямо из бота (без редеплоя).

- звёзды: курс (сколько рублей за одну ⭐️) и кто их продаёт
- отзывы: ссылка на чат/канал с отзывами

По умолчанию — значения из этого файла, но всё перекрывается JSON-файлом
рядом с базой (DATA_DIR на хостинге), поэтому живёт вечно.
"""

import json
import os
import re

_DATA_DIR = os.getenv("DATA_DIR", "")
EXTRAS_FILE = os.path.join(_DATA_DIR, "extras.json") if _DATA_DIR else "extras.json"

# Ссылка на чат с отзывами — взята из описания бота (@AutoRasCad_Bot).
DEFAULT_REVIEWS = "https://t.me/ReBotq"
DEFAULT_STARS_PRICE = 150
# Второй админ — именно он продаёт звёзды.
DEFAULT_STARS_SELLER = "Manhetenn"

_URL_RE = re.compile(r"^(https://)?t\.me/[A-Za-z0-9_]+(/.*)?$")


def load() -> dict:
    try:
        with open(EXTRAS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save(data: dict) -> None:
    folder = os.path.dirname(EXTRAS_FILE)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(EXTRAS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def stars_price() -> int:
    try:
        value = int(load().get("stars_price", DEFAULT_STARS_PRICE))
    except (TypeError, ValueError):
        return DEFAULT_STARS_PRICE
    return value if value > 0 else DEFAULT_STARS_PRICE


def set_stars_price(value: int) -> None:
    data = load()
    data["stars_price"] = int(value)
    save(data)


def stars_seller() -> str:
    return str(load().get("stars_seller") or DEFAULT_STARS_SELLER)


def reviews() -> str:
    url = str(load().get("reviews") or DEFAULT_REVIEWS).strip()
    return url if is_valid_url(url) else DEFAULT_REVIEWS


def set_reviews(url: str) -> bool:
    """Принимает вида t.me/xxx или https://t.me/xxx/123. False = мусор."""
    url = (url or "").strip()
    if not _URL_RE.match(url):
        return False
    if not url.startswith("http"):
        url = "https://" + url
    data = load()
    data["reviews"] = url
    save(data)
    return True


def is_valid_url(url: str) -> bool:
    return bool(_URL_RE.match((url or "").strip()))


def short_url(url: str) -> str:
    """https://t.me/ReBotq -> t.me/ReBotq (для кнопки в панели)."""
    return (url or "").replace("https://", "").replace("http://", "")
