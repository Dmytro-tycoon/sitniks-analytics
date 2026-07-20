"""Канал: окремий Telegram-бот — агент-продавець, що сам веде діалог.

Це і пісочниця (поспілкуйся з агентом сам), і бойовий бот (реальні ліди).
Запуск: python scripts/run_sales_bot.py  (потрібен TELEGRAM_SALES_BOT_TOKEN).
"""
from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from src.consultant.engine import followup_message, respond
from src.consultant.handoff import deliver_handoff
from src.consultant.memory import Conversation, store
from src.consultant.playbook import get_playbook
from src.config import settings

dp = Dispatcher()

# Прискорення часу для пісочниці: 1 = реальні години, напр. 0.001 = тестовий режим.
FOLLOWUP_TIME_SCALE = 1.0


async def _followup_later(bot: Bot, chat_id: int, conv: Conversation, hours: float, marker: int) -> None:
    """Дожим: почекати й написати, якщо клієнт так і не відповів."""
    await asyncio.sleep(hours * 3600 * FOLLOWUP_TIME_SCALE)
    if conv.status != "active" or len(conv.turns) != marker:
        return  # клієнт уже написав або діалог закрито
    res = await followup_message(conv)
    text = res.get("reply", "")
    if not text:
        return
    conv.add("agent", text)
    await bot.send_message(chat_id, text)
    if conv.status == "active" and conv.next_followup_hours > 0:
        asyncio.create_task(_followup_later(bot, chat_id, conv, conv.next_followup_hours, len(conv.turns)))


@dp.message(Command("start"))
async def on_start(message: Message) -> None:
    # Новий діалог для цього користувача
    conv = store.get_or_create(str(message.from_user.id), "telegram")
    conv.turns.clear()
    conv.status = "active"
    conv.stage = "contact"
    await message.answer("Вітаю! 👋 Чим можу допомогти?")


@dp.message()
async def on_message(message: Message) -> None:
    if not message.text:
        return
    conv = store.get_or_create(str(message.from_user.id), "telegram")
    # Уже передано живому консультанту — агент мовчить (веде людина)
    if conv.status == "handoff":
        return
    if conv.status != "active":
        conv.status = "active"  # клієнт повернувся — продовжуємо
    conv.add("client", message.text)

    result = await respond(conv, playbook=get_playbook())
    reply = result.get("reply", "")
    conv.add("agent", reply)
    await message.answer(reply)

    # Готова до підбору → передаємо консультанту (анкета в Telegram-групу)
    if result.get("handoff"):
        await deliver_handoff(
            conv.lead_id, "telegram", result.get("handoff_summary") or "",
            message.from_user.username,
        )
        return

    # Запланувати дожим, якщо клієнтка замовкне
    if conv.status == "active" and conv.next_followup_hours > 0:
        asyncio.create_task(
            _followup_later(message.bot, message.chat.id, conv, conv.next_followup_hours, len(conv.turns))
        )


async def run() -> None:
    bot = Bot(token=settings.TELEGRAM_SALES_BOT_TOKEN)
    print("Агент-продавець запущено (Telegram).")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run())
