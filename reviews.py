"""Живая лента отзывов из ТГК — последние посты под кнопкой «Отзывы».

Откуда берём (по порядку):
  1. Веб-превью публичного канала: https://t.me/s/<username>
  2. Посты, которые бот получает сам — если его добавили админом в ТГК
  3. Диск (DATA_DIR/reviews_cache.json) — чтобы отзывы были даже offline

Всё кешируется: страница каталога никогда не ждёт сеть.
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser

TTL = 300          # перечитывать превью не чаще, чем раз в 5 минут
MAX = 5            # сколько отзывов показывать
TIMEOUT = 8        # секунд на запрос к t.me
MAX_LEN = 400      # обрезаем слишком длинные посты

_DATA_DIR = os.getenv("DATA_DIR", "")
CACHE_FILE = os.path.join(_DATA_DIR, "reviews_cache.json") if _DATA_DIR else "reviews_cache.json"

UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36")

_items: list[dict] = []
_ts: float = 0.0
_loading = False


# ------------------------------------------------------------------ утилиты

def channel_username(link: str) -> str:
    """https://t.me/ReBotq/12 -> ReBotq"""
    m = re.search(r"t\.me/([A-Za-z0-9_]+)", link or "")
    return m.group(1) if m else ""


def _clean(raw: str) -> str:
    """Приводим HTML-текст поста к аккуратному плоскому тексту."""
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in (raw or "").splitlines()]
    text = "\n".join(ln for ln in lines if ln).strip()
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN - 1].rstrip() + "…"
    return text


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ------------------------------------------------------------------ парсер

class _FeedParser(HTMLParser):
    """Вытаскивает текст, дату и ссылку каждого поста из https://t.me/s/<user>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[dict] = []
        self._buf: list[str] = []
        self._depth = 0
        self._in_text = False
        self._in_date = False
        self._pending: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""

        if self._in_text:
            if tag == "div":
                self._depth += 1
                self._buf.append("\n")     # вложенный блок (цитата) — с новой строки
            elif tag == "br":
                self._buf.append("\n")
            return

        if tag == "div" and "tgme_widget_message_text" in cls:
            self._in_text = True
            self._depth = 1
            self._buf = []
            return

        if tag == "a" and "tgme_widget_message_date" in cls and self._pending is not None:
            self._pending["url"] = a.get("href", "")
            self._in_date = True
        elif tag == "time" and self._in_date and a.get("datetime") and self._pending is not None:
            self._pending["date"] = a["datetime"]

    def handle_endtag(self, tag):
        if self._in_text and tag == "div":
            if self._depth > 1:
                self._buf.append("\n")     # конец вложенного блока
            self._depth -= 1
            if self._depth == 0:
                self._in_text = False
                text = _clean("".join(self._buf))
                self._pending = None
                if text:
                    self._pending = {"text": text, "date": "", "url": ""}
            return
        if self._in_date and tag == "a":
            if self._pending:
                self.posts.append(self._pending)
                self._pending = None
            self._in_date = False

    def handle_data(self, data):
        if self._in_text:
            self._buf.append(data)


def parse_feed(html: str) -> list[dict]:
    p = _FeedParser()
    p.feed(html or "")
    return p.posts[:MAX]


# ------------------------------------------------------------------ хранилище

def _save() -> None:
    try:
        folder = os.path.dirname(CACHE_FILE)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_items, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[reviews] не сохранил кеш: {e}")


def _load_disk() -> None:
    global _items, _ts
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            _items = [x for x in data if isinstance(x, dict) and x.get("text")][:MAX]
            _ts = time.time()   # сразу не лезем в сеть при старте
    except (OSError, ValueError, TypeError):
        pass


def recent(limit: int = MAX) -> list[dict]:
    """Синхронно и без I/O — только то, что уже в памяти."""
    return _items[:limit]


def remember(text: str, url: str = "", date: str = "") -> bool:
    """Пост из ТГК (бот — админ канала) сразу в ленту. False = дубль."""
    global _items
    clean = _clean(text)
    if not clean:
        return False
    if url and any(i.get("url") == url for i in _items):
        return False
    item = {"text": clean, "date": date or _now_iso(), "url": url}
    _items = [item] + [i for i in _items if i.get("url") != url]
    _items = _items[:MAX]
    _save()
    return True


# ------------------------------------------------------------------ загрузка

async def refresh(force: bool = False) -> list[dict]:
    """Тянем веб-превью ТГК. Ошибки не роняют ни бота, ни страницу."""
    global _items, _ts, _loading
    if _loading:
        return _items
    if not force and _items and time.time() - _ts < TTL:
        return _items

    import extras

    user = channel_username(extras.reviews())
    if not user:
        return _items

    _loading = True
    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": UA}) as session:
            async with session.get(f"https://t.me/s/{user}") as resp:
                if resp.status != 200:
                    print(f"[reviews] t.me/s/{user} -> HTTP {resp.status}")
                    return _items
                html = await resp.text(errors="ignore")

        posts = parse_feed(html)
        if posts:
            _items = posts
            _ts = time.time()
            _save()
            print(f"[reviews] обновил ленту: {len(posts)} постов из @{user}")
        else:
            print(f"[reviews] @{user}: постов не нашёл (приватный чат?)")
    except Exception as e:                      # noqa: BLE001
        print(f"[reviews] @{user}: {type(e).__name__}: {e}")
    finally:
        _loading = False
    return _items


def kick() -> None:
    """Запросить свежую ленту в фоне, если кеш протух. Ничего не блокирует."""
    if time.time() - _ts < TTL:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(refresh())


async def loop() -> None:
    """Фоновое обновление ленты раз в TTL — работает всё время жизни бота."""
    first = True
    while True:
        try:
            await refresh(force=first)     # при старте тянем сразу, дальше — по TTL
        except Exception as e:             # noqa: BLE001
            print(f"[reviews] фоновое обновление: {type(e).__name__}: {e}")
        first = False
        await asyncio.sleep(TTL)


def start() -> None:
    """Загрузить кеш с диска и у фоновую задачу (вызывается при старте бота)."""
    _load_disk()
    try:
        asyncio.get_running_loop().create_task(loop())
    except RuntimeError:
        pass
