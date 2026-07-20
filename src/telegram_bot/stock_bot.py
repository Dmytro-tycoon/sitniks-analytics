"""Окремий Telegram-бот для закупівель.

Команди:
  /stock  — рекомендований залишок по ключових товарах (розпив + пакування)
  /start, /help — довідка
  /whoami — chat_id
"""
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from src.config import settings
from src.purchasing.stock import (
    compute_recommended_stock,
    format_stock_report,
    DEFAULT_COVERAGE_DAYS,
    DEFAULT_WINDOW_DAYS,
)

# Bot створюємо лише за наявності токена — щоб імпорт main.py не падав,
# поки STOCK_BOT_TOKEN ще не заведено (main.py стартує полінг під тим же if).
stock_bot = (
    Bot(
        token=settings.STOCK_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    if settings.STOCK_BOT_TOKEN
    else None
)
stock_dp = Dispatcher()


@stock_dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    await message.answer(
        "📦 <b>Бот закупівель</b>\n\n"
        "Рахую, скільки має бути на складі за темпом продажів із CRM.\n\n"
        "/stock — рекомендований залишок по ключових товарах\n"
        "/whoami — мій chat_id\n\n"
        f"<i>Логіка: середній продаж/день × {DEFAULT_COVERAGE_DAYS} дн покриття "
        f"(швидкість за {DEFAULT_WINDOW_DAYS} дн).</i>"
    )


@stock_dp.message(Command("whoami"))
async def cmd_whoami(message: Message):
    await message.answer(
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"type: {message.chat.type}"
    )


@stock_dp.message(Command("stock"))
async def cmd_stock(message: Message):
    await message.answer("⏳ Рахую залишок за продажами...")
    try:
        rows = await compute_recommended_stock()
    except Exception as e:
        await message.answer(f"❌ Помилка: {type(e).__name__}: {e}")
        return
    await message.answer(format_stock_report(rows), disable_web_page_preview=True)
