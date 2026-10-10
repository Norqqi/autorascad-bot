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
        "desc": "Номер для регистрации где угодно",
        "price": "130 ₽",
        "prefix": "+1",
        "code": "us",
        "bonus": "🔥 Берут чаще всего: почта, соцсети, мессенджеры",
    },
    {
        "id": 2,
        "name": "🇨🇦 Канада",
        "desc": "Тот же +1, но Канада",
        "price": "130 ₽",
        "prefix": "+1",
        "code": "ca",
        "bonus": "🍁 Заходит, когда США не пускает",
    },
    {
        "id": 3,
        "name": "🇨🇴 Колумбия",
        "desc": "Дёшево и работает",
        "price": "100 ₽",
        "prefix": "+57",
        "code": "co",
        "bonus": "💵 Самая низкая цена в списке",
    },
    {
        "id": 4,
        "name": "🇺🇿 Узбекистан",
        "desc": "СНГ, смс приходит быстро",
        "price": "110 ₽",
        "prefix": "+998",
        "code": "uz",
        "bonus": "🚀 Активация почти мгновенно",
    },
]


def get_product(product_id: int) -> dict | None:
    return next((p for p in PRODUCTS if p["id"] == product_id), None)


def price_of(product: dict) -> str:
    """Цена товара: из prices.json (если админ менял) или из кода."""
    import prices
    return prices.get_price(product["id"], product.get("price", ""))


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
            "price": price_of(p),
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
        f"💰 Цена: <b>{price_of(product)}</b>",
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
        f"(код {product['prefix']}) за {price_of(product)}. Есть в наличии?"
    )
    return f"tg://resolve?domain={seller_username}&text={quote(text)}"


def get_seller(sid: str) -> dict | None:
    return next((s for s in SELLERS if s["id"] == sid), None)


def config_payload(seller: str) -> dict:
    """Данные витрины для мини-приложения (вшиваются в HTML и в /api/config)."""
    import extras

    return {
        "seller": seller,
        "title": STORE_TITLE,
        "description": STORE_DESCRIPTION,
        "starsPrice": extras.stars_price(),
        "starsSeller": extras.stars_seller(),
        "reviews": extras.reviews(),
    }