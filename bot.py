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

import config
import db
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
    await message.answer(
        "Команды:\n"
        "/store — 🛍 каталог номеров (открывается приложением)\n"
        "/unsub — отписаться от уведомлений\n\n"
        "Только для админа:\n"
        "/broadcast &lt;текст&gt; — отправить своё сообщение всем\n"
        "/stats — сколько всего подписчиков\n"
        "/stock — наличие товаров (в наличии / нет)"
    )


@router.message(Command("unsub"))
async def cmd_unsub(message: Message) -> None:
    await db.unsubscribe(message.chat.id)
    await message.answer("🛑 Вы отписались от уведомлений.")


async def on_error(event: ErrorEvent) -> None:
    """Глобальный перехватчик: любая ошибка в обработчиках не роняет бота."""
    print(f"[error] {type(event.exception).__name__}: {event.exception}")


# --------------------------- Команды админа ---------------------------

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message) -> None:
    if not message.from_user or message.from_user.id != config.ADMIN_ID:
        await message.answer("⛔ Только админ может делать рассылку.")
        return

    text = message.text or ""
    _, _, payload = text.partition(" ")  # всё после /broadcast
    if not payload.strip():
        await message.answer("Использование: /broadcast текст рассылки")
        return

    await message.answer("📤 Рассылка началась…")
    ok, failed = await scheduler.broadcast(message.bot, payload.strip())
    await message.answer(f"✅ Готово: доставлено {ok}, ошибок {failed}.")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not message.from_user or message.from_user.id != config.ADMIN_ID:
        await message.answer("⛔ Только админ может смотреть статистику.")
        return
    total, active = await db.count()
    await message.answer(f"Всего подписчиков: {total}\nАктивных: {active}")


# --------------------------- Наличие товаров ---------------------------

def _stock_kb() -> InlineKeyboardMarkup:
    rows = []
    for p in store.PRODUCTS:
        ok = stock.is_available(p["id"])
        mark = "✅" if ok else "❌"
        label = "в наличии" if ok else "нет в наличии"
        rows.append([InlineKeyboardButton(
            text=f"{mark} {p['name']} — {label}",
            callback_data=f"stock:{p['id']}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("stock"))
async def cmd_stock(message: Message) -> None:
    if not message.from_user or message.from_user.id != config.ADMIN_ID:
        return  # просто игнорируем: функционал админа не показываем
    await message.answer(
        "📦 <b>Наличие товаров</b>\n\n"
        "Нажми на строку — наличие переключится.\n"
        "Каталог в приложении обновится сразу, без перезапуска.",
        reply_markup=_stock_kb(),
    )


@router.callback_query(F.data.startswith("stock:"))
async def cb_stock(callback: CallbackQuery) -> None:
    if not callback.from_user or callback.from_user.id != config.ADMIN_ID:
        await callback.answer("⛔ Только админ может менять наличие", show_alert=True)
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
            await callback.message.edit_reply_markup(reply_markup=_stock_kb())
        except Exception:
            pass


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
            {
                "seller": config.ADMIN_USERNAME,
                "title": store.STORE_TITLE,
                "description": store.STORE_DESCRIPTION,
            },
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
