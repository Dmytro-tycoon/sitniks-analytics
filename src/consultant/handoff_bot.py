"""Окремий Telegram-бот для дівчат-консультанток.

Призначення: отримувати від агента анкети клієнток, готових до підбору, разом із
посиланням на діалог у Sitniks. Дівчата пишуть боту /start (або додають його в робочу
групу), а chat_id тієї групи → у змінну TELEGRAM_CONSULTANTS_CHAT_ID.

Токен — окремий, з @BotFather → env HANDOFF_BOT_TOKEN.
Полінг запускається з main.py, якщо токен заданий.
"""
from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from src.config import settings

# Бот створюємо лише якщо токен заданий (інакше aiogram кине помилку на порожньому токені).
handoff_bot: Bot | None = (
    Bot(
        token=settings.HANDOFF_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    if settings.HANDOFF_BOT_TOKEN
    else None
)
handoff_dp = Dispatcher()


@handoff_dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Це бот передачі лідів консультанткам.\n\n"
        "Сюди падатимуть <b>анкети клієнток</b>, готових до підбору, з посиланням на діалог у Sitniks.\n\n"
        f"chat_id цього чату: <code>{message.chat.id}</code>\n"
        "Щоб анкети йшли у вашу робочу групу — додайте цей бот у групу й передайте адміну "
        "її chat_id (команда /whoami у групі)."
    )


@handoff_dp.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    await message.answer(
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"type: {message.chat.type}\n"
        f"title: {message.chat.title or message.chat.full_name or '—'}"
    )


def get_notify_bot() -> Bot:
    """Бот для сповіщень консультанткам: спеціальний, або аналітичний як fallback.

    Поки HANDOFF_BOT_TOKEN не заданий — шлемо через основний бот (щоб передача не ламалась).
    """
    if handoff_bot is not None:
        return handoff_bot
    from src.telegram_bot.bot import bot as analytics_bot

    return analytics_bot


async def run() -> None:
    """Запуск полінгу (для /start, /whoami). Викликається з main.py за наявності токена."""
    if handoff_bot is not None:
        await handoff_dp.start_polling(handoff_bot)
