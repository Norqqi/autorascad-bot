"""Локальный сервер мини-приложения (Telegram Web App).

Запуск:  python webapp.py
Порт:    WEBAPP_PORT из .env, по умолчанию 8080.

ВНИМАНИЕ: Telegram требует HTTPS. Локально это только для разработки,
доступ из телефона даёт туннель (например cloudflared):
    cloudflared tunnel --url http://127.0.0.1:8080
"""

import json
import os
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv

import store

load_dotenv()

HERE = Path(__file__).parent
INDEX_HTML = HERE / "webapp" / "index.html"
PORT = int(os.getenv("WEBAPP_PORT", "8080"))


def _public_products() -> list[dict]:
    return store.public_products()


async def api_products(request: web.Request) -> web.Response:
    return web.json_response(store.public_products(), dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def api_config(request: web.Request) -> web.Response:
    return web.json_response({
        "title": store.STORE_TITLE,
        "description": store.STORE_DESCRIPTION,
        "seller": os.getenv("ADMIN_USERNAME", ""),
    }, dumps=lambda o: json.dumps(o, ensure_ascii=False))


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(INDEX_HTML)


def main() -> None:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/products", api_products)
    app.router.add_get("/api/config", api_config)
    print(f"[webapp] Сервер запущен на http://127.0.0.1:{PORT}")
    web.run_app(app, port=PORT, print=lambda *a, **k: None)


if __name__ == "__main__":
    main()