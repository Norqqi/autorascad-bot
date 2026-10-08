"""Генератор статической версии мини-приложения: webapp/catalog.html.

Данные (товары + продавец) вшиваются прямо в HTML, поэтому файл можно
выложить на любой статический HTTPS-хостинг (catbox.moe, GitHub Pages и т.п.)
и вписать ссылку в .env как WEBAPP_URL.

Запуск:  python gen_static.py
"""

import json
from pathlib import Path

import config
import store

HERE = Path(__file__).parent
TEMPLATE = HERE / "webapp" / "index.html"
OUT = HERE / "webapp" / "catalog.html"

MARKER = "let injected = window.__CATALOG_DATA__ || null;"


def build_payload() -> dict:
    return {
        "config": {
            "seller": config.ADMIN_USERNAME,
            "title": store.STORE_TITLE,
            "description": store.STORE_DESCRIPTION,
        },
        "products": store.public_products(),
    }


def render() -> str:
    """Возвращает HTML каталога с вшитыми данными (товары + продавец)."""
    html = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in html:
        raise RuntimeError("Не нашёл маркер данных в шаблоне webapp/index.html")
    data = json.dumps(build_payload(), ensure_ascii=False).replace("</", "<\\/")
    return html.replace(
        MARKER,
        f"let injected = window.__CATALOG_DATA__ = {data};",
    )


def main() -> None:
    OUT.write_text(render(), encoding="utf-8")
    print(f"[gen_static] ОК: {OUT} ({OUT.stat().st_size} байт)")


if __name__ == "__main__":
    main()