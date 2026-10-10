"""Telegram-бот: рассылка и напоминания по расписанию (aiogram 3, polling)"""

import asyncio
import socket

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

import admins
import config
import db
import extras
import prices
import scheduler
import stock
import store

router = Router()


def make_session():
    """Сессия aiohttp. Если TELEGRAM_API_IP задан — ходим на этот IP
    (обход блокировки api.telegram.org провайдером)."""
    from aiogram.client.session.aiohttp import AiohttpSession

    api_ip = config.TELEGRAM_API_IP
    if not api_ip:
        return AiohttpSession(timeout=15)

    from aiohttp import abc

    class _Resolver(abc.AbstractResolver):
        # Основной IP + запасные: 220 работает, остальные пробуются как fallback
        CANDIDATES = ["149.154.167.220", "149.154.167.221", "149.154.167.222",
                      "149.154.167.223", "149.154.166.110", "91.108.56.130"]

        async def resolve(self, host, port=0, family=socket.AF_INET):
            if host == "api.telegram.org":
                cands = [api_ip, *self.CANDIDATES] if api_ip not in self.CANDIDATES else self.CANDIDATES
            else:
                cands = [host]
            result = []
            for cand in cands:
                try:
                    infos = socket.getaddrinfo(cand, port, family=family, type=socket.SOCK_STREAM)
                except socket.gaierror:
                    continue
                for info in infos:
                    result.append({
                        "hostname": cand,
                        "host": info[4][0],
                        "port": info[4][1],
                        "family": info[0],
                        "proto": info[1],
                    })
            return result

        async def close(self):
            pass

    class _Session(AiohttpSession):
        def __init__(self):
            super().__init__()
            self._connector_init["resolver"] = _Resolver()

    return _Session()


# ------------------------- Пользовательские команды -------------------------

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    user = message.from_user
    await db.subscribe(
        message.chat.id,
        user.username if user else None,
    )
    await message.answer(
        "Привет! 👋\n\n"
        "🛍 <b>VirtualBot</b> — каталог виртуальных номеров.\n\n"
        "Команды:\n"
        "• /store — открыть каталог\n"
        "• /unsub — отписаться от уведомлений\n\n"
        "Ты уже подписан на уведомления автоматически. 😉"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    text = (
        "Команды:\n"
        "/store — 🛍 каталог номеров (открывается приложением)\n"
        "/unsub — отписаться от уведомлений"
    )
    if _is_admin(message.from_user):
        text += (
            "\n\n<b>Только для админа:</b>\n"
            "/admin — 🎛 админ-панель (наличие, цены, админы)\n"
            "/price — 💰 цены: меню или <code>/price 2 150</code>\n"
            "/stars — ⭐️ цена звезды: <code>/stars 150</code>\n"
            "/reviews — 💬 ссылка на чат отзывов\n"
            "/broadcast &lt;текст&gt; — отправить своё сообщение всем\n"
            "/add @username — дать права админа\n"
            "/del @username — забрать права\n"
            "/admins — список админов"
        )
    await message.answer(text)


@router.message(Command("unsub"))
async def cmd_unsub(message: Message) -> None:
    await db.unsubscribe(message.chat.id)
    await message.answer("🛑 Вы отписались от уведомлений.")


async def on_error(event: ErrorEvent) -> None:
    """Глобальный перехватчик: любая ошибка в обработчиках не роняет бота."""
    print(f"[error] {type(event.exception).__name__}: {event.exception}")


# --------------------------- Команды админа ---------------------------

# Чаты, в которых бот ждёт ответ текстом (username нового админа
# или новая цена товара). Ключ — id чата, значение — что ждём.
_pending: dict[int, dict] = {}


def _is_admin(user) -> bool:
    """Главный админ (ADMIN_ID) + все добавленные через /add."""
    if not user:
        return False
    return admins.is_admin(user.id, config.ADMIN_ID)


def _cb_chat(callback: CallbackQuery) -> int:
    """Чат, в котором жмут кнопку (для ожидания текстового ответа)."""
    if callback.message:
        return callback.message.chat.id
    return callback.from_user.id


_RESOLVE_HINT = """Как найти:
• юзернейм должен быть точным (как в профиле, без пробелов)
• человек должен <b>хоть раз написать боту</b> — тогда он есть в базе
• либо пришли <b>числовой ID</b>: <code>/add 123456789</code>"""


async def _resolve_user(bot: Bot, ref: str) -> tuple[int, str] | None:
    """@username / username / числовой ID -> (user_id, username)."""
    ref = (ref or "").strip().split()[0].lstrip("@")
    if not ref:
        return None

    # 1) Числовой ID — сработает всегда
    if ref.isdigit():
        uid = int(ref)
        uname = await db.get_username(uid) or ""
        return uid, uname

    # 2) Своя база подписчиков (надёжно: Telegram не всегда отдаёт боту
    #    пользователя по нику, а мы храним ник каждого, кто писал боту)
    found = await db.find_by_username(ref)
    if found:
        return found

    # 3) API Telegram — на случай, если человек ещё не писал боту
    try:
        chat = await bot.get_chat(ref)
    except Exception as e:
        print(f"[admin] get_chat({ref}): {e}")
        return None
    if chat is None or chat.type != "private":
        return None
    return chat.id, (chat.username or ref)


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message) -> None:
    if not _is_admin(message.from_user):
        return  # молча игнорируем

    text = message.text or ""
    _, _, payload = text.partition(" ")  # всё после /broadcast
    if not payload.strip():
        await message.answer("Использование: /broadcast текст рассылки")
        return

    await message.answer("📤 Рассылка началась…")
    ok, failed = await scheduler.broadcast(message.bot, payload.strip())
    await message.answer(f"✅ Готово: доставлено {ok}, ошибок {failed}.")


@router.message(Command("add"))
async def cmd_add(message: Message) -> None:
    if not _is_admin(message.from_user):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Использование:\n<code>/add @username</code>\n\n"
            "Или нажми «👥 Админы» в панели → «➕ Добавить админа»."
        )
        return

    found = await _resolve_user(message.bot, parts[1])
    if not found:
        await message.answer("❌ Не нашёл такого пользователя.\n\n" + _RESOLVE_HINT)
        return

    uid, uname = found
    if uid == config.ADMIN_ID:
        await message.answer("Это главный админ — его и так все права 🙂")
        return
    name = admins.display_name(uid, uname)
    if admins.is_admin(uid, config.ADMIN_ID):
        await message.answer(f"ℹ️ {name} уже админ.")
        return

    admins.add(uid, uname)
    await message.answer(f"✅ {name} теперь админ.\n👥 /admins — список")


@router.message(Command("del"))
async def cmd_del(message: Message) -> None:
    if not _is_admin(message.from_user):
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: <code>/del @username</code>")
        return

    found = await _resolve_user(message.bot, parts[1])
    if not found:
        await message.answer("❌ Не нашёл такого пользователя.\n\n" + _RESOLVE_HINT)
        return

    uid, uname = found
    if uid == config.ADMIN_ID:
        await message.answer("⛔ Главного админа нельзя удалить.")
        return
    name = admins.display_name(uid, uname)
    if admins.remove(uid):
        await message.answer(f"🛑 {name} больше не админ.")
    else:
        await message.answer(f"ℹ️ {name} и так не админ.")


@router.message(Command("admins"))
async def cmd_admins(message: Message) -> None:
    if not _is_admin(message.from_user):
        return
    await message.answer(_admins_text(), reply_markup=_admin_list_kb())


# --------------------------- Админ-панель ---------------------------

def _panel_kb() -> InlineKeyboardMarkup:
    rows = []
    for p in store.PRODUCTS:
        ok = stock.is_available(p["id"])
        mark = "✅" if ok else "❌"
        label = "в наличии" if ok else "нет в наличии"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {p['name']} — {label}",
            callback_data=f"stock:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(
        text=f"💰 Цены ({len(prices.load_all())} изменено)",
        callback_data="pr:list",
    )])
    rows.append([InlineKeyboardButton(
        text=f"⭐️ Звёзды — {extras.stars_price()} ₽ за штуку",
        callback_data="pr:stars",
    )])
    rows.append([InlineKeyboardButton(
        text=f"💬 Отзывы — {extras.short_url(extras.reviews())}",
        callback_data="pr:reviews",
    )])
    rows.append([InlineKeyboardButton(
        text=f"👥 Админы ({len(admins.load()) + 1})",
        callback_data="adm:list",
    )])
    rows.append([InlineKeyboardButton(
        text="➕ Добавить админа",
        callback_data="adm:add",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


PANEL_TEXT = (
    "🎛 <b>Админ-панель</b>\n\n"
    "<b>Наличие</b> — тапни строку товара, он пропадёт/появится в каталоге\n"
    "<b>Цены</b> — «💰 Цены», потом тап по товару и пришли новую сумму\n"
    "<b>⭐️ Звёзды</b> — тап, потом пришли цену за штуку (например 150)\n"
    "<b>💬 Отзывы</b> — тап, потом пришли ссылку на чат (t.me/xxx)\n"
    "<b>Админы</b> — «👥» и «➕»\n\n"
    "Всё применяется сразу, перезапуск не нужен."
)


def _prices_kb() -> InlineKeyboardMarkup:
    rows = []
    for p in store.PRODUCTS:
        base = p["price"]
        now = store.price_of(p)
        mark = "✏️ " if now != base else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark}{p['name']} — {now}",
            callback_data=f"pr:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(
        text="↩️ Сбросить все цены",
        callback_data="pr:resetall",
    )])
    rows.append([InlineKeyboardButton(
        text="◀️ Назад к панели",
        callback_data="pr:back",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _admins_text() -> str:
    main = f"👑 id {config.ADMIN_ID} — главный (нельзя удалить)"
    extra = admins.load()
    if not extra:
        return "👥 <b>Админы</b>\n\n" + main + "\n\nДругих нет."
    lines = [main]
    for uid, uname in extra.items():
        lines.append(f"• {admins.display_name(uid, uname)}")
    return "👥 <b>Админы</b>\n\n" + "\n".join(lines)


def _admin_list_kb() -> InlineKeyboardMarkup:
    rows = []
    for uid, uname in admins.load().items():
        rows.append([InlineKeyboardButton(
            text=f"🛑 Убрать {admins.display_name(uid, uname)}",
            callback_data=f"adm:del:{uid}",
        )])
    rows.append([InlineKeyboardButton(
        text="➕ Добавить админа",
        callback_data="adm:add",
    )])
    rows.append([InlineKeyboardButton(
        text="◀️ Назад к панели",
        callback_data="adm:back",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _open_panel(message: Message) -> None:
    await message.answer(PANEL_TEXT, reply_markup=_panel_kb())


@router.message(Command("stock"))
async def cmd_stock(message: Message) -> None:
    if not _is_admin(message.from_user):
        return  # молча: функционал админа не показываем
    await _open_panel(message)


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user):
        return
    await _open_panel(message)


@router.callback_query(F.data.startswith("stock:"))
async def cb_stock(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user):
        await callback.answer("⛔ Только для админа", show_alert=True)
        return

    try:
        pid = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Ошибка 😕")
        return

    if not store.get_product(pid):
        await callback.answer("Товар не найден 😔")
        return

    new_state = stock.toggle(pid)
    product = store.get_product(pid) or {}
    name = product.get("name", f"#{pid}")
    await callback.answer(
        f"{name}: {'✅ в наличии' if new_state else '❌ нет в наличии'}"
    )

    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=_panel_kb())
        except Exception:
            pass


@router.callback_query(F.data.startswith("adm:"))
async def cb_admins(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user):
        await callback.answer("⛔ Только для админа", show_alert=True)
        return

    action = callback.data.split(":", 2)[1]

    if action == "add":
        chat_id = callback.message.chat.id if callback.message else callback.from_user.id
        _pending[chat_id] = {"kind": "admin"}
        await callback.answer()
        await callback.message.answer(
            "➕ Пришли <b>@username</b> (или числовой ID) нового админа.\n"
            "Отмена — /cancel"
        )
        return

    if action == "del":
        try:
            uid = int(callback.data.split(":", 2)[2])
        except (ValueError, IndexError):
            await callback.answer("Ошибка 😕")
            return
        if uid == config.ADMIN_ID:
            await callback.answer("⛔ Главного админа нельзя удалить", show_alert=True)
            return
        admins.remove(uid)
        await callback.answer("🛑 Админ удалён")
        try:
            await callback.message.edit_text(_admins_text(), reply_markup=_admin_list_kb())
        except Exception:
            pass
        return

    if action == "back":
        await callback.answer()
        try:
            await callback.message.edit_text(
                PANEL_TEXT, reply_markup=_panel_kb()
            )
        except Exception:
            pass
        return

    # action == "list"
    await callback.answer()
    await callback.message.answer(_admins_text(), reply_markup=_admin_list_kb())


# ----------------------------- Редактор цен -----------------------------

PRICE_TEXT = (
    "💰 <b>Цены</b>\n\n"
    "Тапни товар и пришли новую сумму (просто число, например <code>150</code>).\n"
    "Каталог в приложении обновится сразу — ничего перезапускать не надо.\n"
    "✏️ — цена уже отличается от той, что в коде."
)


def _find_product(ref: str) -> dict | None:
    """«2» / «США» / «сша» -> товар."""
    ref = (ref or "").strip()
    if ref.isdigit():
        return store.get_product(int(ref))
    low = ref.lower()
    return next((p for p in store.PRODUCTS if low in p["name"].lower()), None)


async def _set_price(message: Message, ref: str, raw: str) -> None:
    product = _find_product(ref)
    if not product:
        names = ", ".join(f"{p['id']}={p['name']}" for p in store.PRODUCTS)
        await message.answer(f"❌ Такого товара нет.\nЕсть: {names}")
        return

    new_price = prices.parse(raw)
    if not new_price:
        await message.answer("❌ Нужно число: <code>150</code> или <code>150 ₽</code>.")
        return

    old = store.price_of(product)
    prices.set_price(product["id"], new_price)
    await message.answer(
        f"✅ <b>{product['name']}</b>: {old} → <b>{new_price}</b>\n"
        f"Каталог уже показывает новую цену.",
        reply_markup=_prices_kb(),
    )


@router.message(Command("price"))
async def cmd_price(message: Message) -> None:
    if not _is_admin(message.from_user):
        return

    args = (message.text or "").split(maxsplit=2)
    if len(args) >= 3:            # /price 2 150  — сразу поменять
        await _set_price(message, args[1], args[2])
        return
    await message.answer(PRICE_TEXT, reply_markup=_prices_kb())


@router.message(Command("stars"))
async def cmd_stars(message: Message) -> None:
    """Цена за одну звезду для вкладки «Звёзды» в каталоге."""
    if not _is_admin(message.from_user):
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) == 2:
        value = prices.to_int(args[1])
        if not value:
            await message.answer("❌ Приши просто число: <code>/stars 150</code>")
            return
        extras.set_stars_price(value)
        await message.answer(
            f"✅ За 1 ⭐️ теперь <b>{extras.stars_price()} ₽</b>. "
            f"В каталоге цена уже новая."
        )
        return

    await message.answer(
        f"⭐️ Сейчас за 1 звезду: <b>{extras.stars_price()} ₽</b>\n"
        f"Продавец: @{extras.stars_seller()}\n\n"
        f"Поменять: <code>/stars 150</code>"
    )


@router.message(Command("reviews"))
async def cmd_reviews(message: Message) -> None:
    """Ссылка на чат с отзывами во вкладке «Отзывы»."""
    if not _is_admin(message.from_user):
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) == 2:
        if not extras.set_reviews(args[1]):
            await message.answer(
                "❌ Нужна ссылка вида <code>t.me/MyChat</code> или "
                "<code>https://t.me/MyChat</code>"
            )
            return
        await message.answer(
            f"✅ Вкладка «Отзывы» ведёт на <code>{extras.short_url(extras.reviews())}</code>"
        )
        return

    await message.answer(
        f"💬 Сейчас стоит: <code>{extras.short_url(extras.reviews())}</code>\n\n"
        f"Поменять: <code>/reviews t.me/МойЧат</code>"
    )


@router.callback_query(F.data.startswith("pr:"))
async def cb_prices(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user):
        await callback.answer("⛔ Только для админа", show_alert=True)
        return

    arg = callback.data.split(":", 2)[1]

    if arg == "back":
        await callback.answer()
        try:
            await callback.message.edit_text(
                PANEL_TEXT, reply_markup=_panel_kb()
            )
        except Exception:
            pass
        return

    if arg == "list":
        await callback.answer()
        await callback.message.answer(PRICE_TEXT, reply_markup=_prices_kb())
        return

    if arg == "resetall":
        for p in store.PRODUCTS:
            prices.reset(p["id"])
        await callback.answer("↩️ Все цены вернулись к базовым")
        try:
            await callback.message.edit_reply_markup(reply_markup=_prices_kb())
        except Exception:
            pass
        return

    if arg == "stars":
        _pending[_cb_chat(callback)] = {"kind": "stars"}
        await callback.answer()
        await callback.message.answer(
            f"⭐️ Сейчас за 1 звезду просят <b>{extras.stars_price()} ₽</b>.\n"
            f"Приши новую цену простым числом, например <code>150</code>.\n"
            f"Отмена — /cancel"
        )
        return

    if arg == "reviews":
        _pending[_cb_chat(callback)] = {"kind": "reviews"}
        await callback.answer()
        await callback.message.answer(
            f"💬 Сейчас ведёт на <code>{extras.short_url(extras.reviews())}</code>\n"
            f"Приши ссылку на чат отзывов (типа <code>t.me/MyChat</code>).\n"
            f"Отмена — /cancel"
        )
        return

    if not arg.isdigit() or not store.get_product(int(arg)):
        await callback.answer("Товар не найден 😕")
        return

    product = store.get_product(int(arg))
    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    _pending[chat_id] = {"kind": "price", "pid": product["id"]}
    await callback.answer()
    await callback.message.answer(
        f"✏️ Приши новую цену для <b>{product['name']}</b>.\n"
        f"Сейчас: <b>{store.price_of(product)}</b>\n"
        f"Просто число, например <code>150</code>. Отмена — /cancel"
    )


# -------------------------------- Маркет --------------------------------

async def seller_username(bot: Bot) -> str:
    """Username продавца: из .env или узнаём у Telegram автоматически."""
    if config.ADMIN_USERNAME:
        return config.ADMIN_USERNAME
    try:
        chat = await bot.get_chat(config.ADMIN_ID)
        config.ADMIN_USERNAME = chat.username or ""
        if config.ADMIN_USERNAME:
            print(f"[store] Продавец: @{config.ADMIN_USERNAME}")
    except Exception as e:
        print(f"[store] Не удалось узнать username админа: {e}")
    return config.ADMIN_USERNAME


@router.message(Command("store"))
async def cmd_store(message: Message) -> None:
    # Каталог живёт в мини-приложении — открываем только его.
    if config.WEBAPP_URL:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🛍 Открыть каталог",
                web_app=WebAppInfo(url=config.WEBAPP_URL),
            )
        ]])
        await message.answer(
            "🛍 <b>Каталог номеров VirtualBot</b>\n\n"
            "Нажми кнопку ниже — откроется каталог с регионами и ценами.",
            reply_markup=kb,
        )
        return

    # Запасной вариант: домен ещё не настроен — прежний список кнопок.
    username = await seller_username(message.bot)
    if not username:
        await message.answer(
            "⚠️ Каталог временно недоступен — домен приложения не настроен."
        )
        return

    buttons = [
        InlineKeyboardButton(
            text=(
                f"❌ {p['name']} — нет в наличии"
                if not stock.is_available(p["id"])
                else f"{p['name']} — {p['price']}"
            ),
            callback_data=f"store:prod:{p['id']}",
        )
        for p in store.PRODUCTS
    ]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    )
    await message.answer("📞 Доступные номера:", reply_markup=kb)


@router.callback_query(F.data.startswith("store:prod:"))
async def cb_store_product(callback: CallbackQuery) -> None:
    product = store.get_product(int(callback.data.rsplit(":", 1)[1]))
    if not product:
        await callback.answer("Товар не найден 😔")
        return
    await callback.answer()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Купить у продавца 1 (@mooredxz)",
            callback_data=f"store:buy:{product['id']}:owner",
        )],
        [InlineKeyboardButton(
            text="Купить у продавца 2 (@Manhetenn)",
            callback_data=f"store:buy:{product['id']}:man",
        )],
        [InlineKeyboardButton(text="◀️ Назад к каталогу", callback_data="store:back")],
    ])

    try:
        await callback.message.answer_photo(
            photo=store.product_image(product),
            caption=store.product_caption(product),
            reply_markup=kb,
        )
    except Exception:
        await callback.message.answer(
            store.product_caption(product),
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("store:buy:"))
async def cb_store_buy(callback: CallbackQuery) -> None:
    parts = callback.data.split(":", 3)
    pid = int(parts[2])
    sid = parts[3] if len(parts) > 3 else "owner"
    product = store.get_product(pid)
    seller = store.get_seller(sid)
    if not product or not seller:
        await callback.answer("Ошибка выбора 🤷")
        return
    await callback.answer()
    url = store.buy_link(seller["username"], product)
    await callback.message.answer(
        f"Выбран продавец: <b>{seller['username']}</b>\n\n"
        "👇 Нажми кнопку ниже, чтобы открыть чат и написать продавцу с готовым сообщением",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Открыть чат с продавцом", url=url),
        ]]),
    )


@router.callback_query(F.data == "store:back")
async def cb_store_back(callback: CallbackQuery) -> None:
    await callback.answer()
    username = await seller_username(callback.bot)
    if not username:
        return
    buttons = [
        InlineKeyboardButton(
            text=(
                f"❌ {p['name']} — нет в наличии"
                if not stock.is_available(p["id"])
                else f"{p['name']} — {p['price']}"
            ),
            callback_data=f"store:prod:{p['id']}",
        )
        for p in store.PRODUCTS
    ]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    )
    await callback.message.answer("📞 Доступные номера:", reply_markup=kb)


# ------------------------- Автоподписка -------------------------
# Обработчик зарегистрирован ПОСЛЕДНИМ: все известные команды выше
# срабатывают первыми, а любое другое сообщение просто оформляет подписку.

@router.message()
async def auto_subscribe(message: Message) -> None:
    user = message.from_user

    # Ждём текст от админа: @username нового админа или новую цену
    task = _pending.pop(message.chat.id, None)
    if task and _is_admin(message.from_user):
        text = (message.text or "").strip()

        if text.lower() in {"/cancel", "cancel", "отмена"}:
            await message.answer("✋ Отменил.")
            return

        if task.get("kind") == "price":
            new_price = prices.parse(text)
            if not new_price:
                _pending[message.chat.id] = task   # даём попробовать снова
                await message.answer(
                    "❌ Это не похоже на цену. Приши просто число: <code>150</code>\n"
                    "Отмена — /cancel"
                )
                return
            product = store.get_product(task.get("pid", -1))
            if not product:
                await message.answer("❌ Товар пропал 😕")
                return
            old = store.price_of(product)
            prices.set_price(product["id"], new_price)
            await message.answer(
                f"✅ <b>{product['name']}</b>: {old} → <b>{new_price}</b>\n"
                f"Каталог уже показывает новую цену.",
                reply_markup=_prices_kb(),
            )
            return

        if task.get("kind") == "stars":
            value = prices.to_int(text)
            if not value:
                _pending[message.chat.id] = task
                await message.answer(
                    "❌ Приши просто число: <code>150</code>\nОтмена — /cancel"
                )
                return
            old = extras.stars_price()
            extras.set_stars_price(value)
            await message.answer(
                f"✅ За 1 ⭐️: {old} ₽ → <b>{extras.stars_price()} ₽</b>\n"
                f"В каталоге цена уже новая."
            )
            return

        if task.get("kind") == "reviews":
            if not extras.set_reviews(text):
                _pending[message.chat.id] = task
                await message.answer(
                    "❌ Нужна ссылка вида <code>t.me/MyChat</code>\nОтмена — /cancel"
                )
                return
            await message.answer(
                f"✅ Вкладка «Отзывы» ведёт на "
                f"<code>{extras.short_url(extras.reviews())}</code>"
            )
            return

        # kind == "admin"
        found = await _resolve_user(message.bot, text)
        if not found:
            _pending[message.chat.id] = task  # даём попробовать снова
            await message.answer(
                "❌ Не нашёл такого пользователя.\n\n" + _RESOLVE_HINT
            )
            return

        uid, uname = found
        name = admins.display_name(uid, uname)
        if uid == config.ADMIN_ID:
            await message.answer("Это главный админ — ему и так всё можно 🙂")
        else:
            if not admins.is_admin(uid, config.ADMIN_ID):
                admins.add(uid, uname)
            await message.answer(f"✅ {name} теперь админ.\n👥 /admins — список")
        return
    if task:
        # Ответ пришёл не от админа — ждём дальше
        _pending[message.chat.id] = task

    # Автоподписка: любое сообщение = подписка на уведомления
    await db.ensure_subscribed(
        message.chat.id,
        user.username if user else None,
    )


# ------------------------------- Запуск -------------------------------

async def start_webapp_server() -> None:
    """Веб-сервер мини-приложения: отдаёт каталог по домену (HTTPS)."""
    import json

    from aiohttp import web

    import gen_static

    async def index(request: web.Request) -> web.Response:
        return web.Response(text=gen_static.render(), content_type="text/html")

    async def health(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    async def api_products(request: web.Request) -> web.Response:
        return web.json_response(
            store.public_products(),
            dumps=lambda o: json.dumps(o, ensure_ascii=False),
        )

    async def api_config(request: web.Request) -> web.Response:
        return web.json_response(
            store.config_payload(config.ADMIN_USERNAME),
            dumps=lambda o: json.dumps(o, ensure_ascii=False),
        )

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/api/products", api_products)
    app.router.add_get("/api/config", api_config)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    print(f"[web] Мини-приложение слушает 0.0.0.0:{config.PORT}")


async def main() -> None:
    bot = Bot(
        config.BOT_TOKEN,
        session=make_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)
    dp.errors.register(on_error)

    await db.init()

    # Если раньше был настроен webhook — снимаем, чтобы работал polling.
    try:
        await bot.delete_webhook()
    except Exception as e:
        print(f"[startup] delete_webhook: {e}")

    # Мини-приложение (нужно, если включён домен Bothost).
    try:
        await start_webapp_server()
    except Exception as e:
        print(f"[web] Мини-приложение не поднялось: {e}")

    # Установка команд меню — не критична: если сеть сейчас нестабильна,
    # пропускаем, бот всё равно должен запуститься.
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Начать работу с ботом"),
            BotCommand(command="store", description="🛍 Каталог номеров"),
            BotCommand(command="unsub", description="Отписаться от уведомлений"),
            BotCommand(command="help", description="Помощь"),
        ])
    except Exception as e:
        print(f"[startup] set_my_commands не прошла: {e}")

    # Кнопка меню чата («≡») сразу открывает мини-приложение каталога.
    if config.WEBAPP_URL:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🛍 Каталог",
                    web_app=WebAppInfo(url=config.WEBAPP_URL),
                )
            )
        except Exception as e:
            print(f"[startup] set_chat_menu_button не прошла: {e}")

    scheduler.start(bot)  # ежедневные уведомления по NOTIFY_TIMES

    print("Бот запущен (polling). Ctrl+C для остановки.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    import time

    # Внешний цикл: если процесс аварийно упал (нестабильная сеть и т.п.) —
    # автоматически перезапускаемся.
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[restart] Бот упал: {e!r}. Перезапуск через 10 секунд…")
        time.sleep(10)
