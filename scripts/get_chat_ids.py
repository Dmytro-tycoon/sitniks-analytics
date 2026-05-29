"""Запусти, попроси менеджерів і керівників написати боту /start
або додати в групу. Бот покаже їхні chat_id."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from src.config import settings

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


@dp.message()
async def echo(message: Message):
    chat = message.chat
    user = message.from_user
    info = (
        f"📋 <b>Інформація для config:</b>\n\n"
        f"<b>chat_id:</b> <code>{chat.id}</code>\n"
        f"<b>chat type:</b> {chat.type}\n"
        f"<b>chat title:</b> {chat.title or '-'}\n"
        f"<b>user:</b> @{user.username or '-'}\n"
        f"<b>name:</b> {user.full_name}\n"
    )
    print(f"[{user.full_name} | @{user.username}] chat_id={chat.id} type={chat.type}")
    await message.answer(info, parse_mode="HTML")


async def main():
    print("Бот запущено. Напишіть йому /start або додайте в групу.")
    print("Ctrl+C — зупинити.\n")
    await dp.start_polling(bot)


asyncio.run(main())
