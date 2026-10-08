"""Мини-маркет: товары, карточки и кнопка покупки.

Каталог одним сообщением: кнопка с номером -> карточка страны (фото, цена,
бонус) -> кнопка «Купить» открывает ЛС продавца с готовым сообщением.

Как поменять товары: отредактируй список PRODUCTS ниже.
- code: код страны для флага (flagcdn.com), например "us", "ca", "co", "uz"
"""

from random import choice
from urllib.parse import quote

# Заголовок каталога (показывается в чате)
STORE_TITLE = "‼️ • Продажа физических номеров #Thx 👁"
STORE_DESCRIPTION = "В наличии такие регионы как: 💎"

# Случайные «приколы», добавляются в карточку товара
BONUSES = [
    "⚡️ Выдача номера за 5 минут после оплаты",
    "🎁 Подарок: −10% на второй номер в корзине",
    "🔒 Анонимная выдача, без привязки к твоим данным",
    "📲 Поддержка 24/7 — помогу с любым вопросом",
    "💳 Оплата удобным способом, без комиссии",
    "🕒 Номер только твой, продаём без дублей",
]

# Продавцы для выбора при покупке
SELLERS = [
    {"id": "owner", "username": "mooredxz", "label": "Продавец 1 (@mooredxz)"},
    {"id": "man", "username": "Manhetenn", "label": "Продавец 2 (@Manhetenn)"},
]

PRODUCTS = [
    {
        "id": 1,
        "name": "🇺🇸 США",
        "desc": "Самый популярный регион для верификаций",
        "price": "130 ₽",
        "prefix": "+1",
        "code": "us",
        "bonus": "🔥 Ходовой: смс-верификация почты, соцсетей, сервисов",
    },
    {
        "id": 2,
        "name": "🇨🇦 Канада",
        "desc": "Северная Америка, стабильный номер",
        "price": "130 ₽",
        "prefix": "+1",
        "code": "ca",
        "bonus": "🍁 Отличный выбор для зарубежных сервисов",
    },
    {
        "id": 3,
        "name": "🇨🇴 Колумбия",
        "desc": "Южная Америка, бюджетная верификация",
        "price": "100 ₽",
        "prefix": "+57",
        "code": "co",
        "bonus": "💵 Самый выгодный вариант в каталоге",
    },
    {
        "id": 4,
        "name": "🇺🇿 Узбекистан",
        "desc": "СНГ, быстрая активация",
        "price": "110 ₽",
        "prefix": "+998",
        "code": "uz",
        "bonus": "🚀 Активация почти мгновенная",
    },
]


def get_product(product_id: int) -> dict | None:
    return next((p for p in PRODUCTS if p["id"] == product_id), None)


def public_products() -> list[dict]:
    """Товары для мини-приложения: флаг отдельно от названия + наличие."""
    import stock

    avail = stock.load_all()
    out = []
    for p in PRODUCTS:
        name = p["name"]
        flag = name.split(" ", 1)[0] if name else ""
        out.append({
            "id": p["id"],
            "name": name.replace(flag, "").strip() if flag else name,
            "flag": flag,
            "prefix": p.get("prefix", ""),
            "price": p["price"],
            "desc": p.get("desc", ""),
            "bonus": p.get("bonus", ""),
            "available": avail.get(p["id"], True),
        })
    return out


def product_image(product: dict) -> str:
    """Флаг страны (фото) для карточки товара."""
    return f"https://flagcdn.com/w320/{product['code']}.png"


def product_caption(product: dict) -> str:
    """Подпись к фото: цена, бонус, подсказка."""
    perks = [product["bonus"], choice(BONUSES)]
    lines = [
        f"<b>{product['name']}</b>",
        product["desc"],
        f"📞 Код страны: <code>{product['prefix']}</code>",
        "",
        f"💰 Цена: <b>{product['price']}</b>",
        *[f"✨ {p}" for p in perks],
        "",
        "👇 Жми «Купить» — откроется чат со мной с готовым сообщением",
    ]
    return "\n".join(lines)


def buy_link(seller_username: str, product: dict) -> str:
    """Нативная ссылка: открывает ЛС продавца с готовым сообщением.

    Используем tg://resolve — такой клиент Telegram открывает чат напрямую,
    без промежуточного браузера/«избранного».
    """
    text = (
        f"Здравствуйте! Хочу купить номер {product['name']} "
        f"(код {product['prefix']}) за {product['price']}. Есть в наличии?"
    )
    return f"tg://resolve?domain={seller_username}&text={quote(text)}"


def get_seller(sid: str) -> dict | None:
    return next((s for s in SELLERS if s["id"] == sid), None)