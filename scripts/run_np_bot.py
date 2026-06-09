"""Локальний запуск тільки NP-бота (без основного та ads-бота — щоб не конфліктувати з Railway)."""
import asyncio
from src.telegram_bot.np_bot import np_bot, np_dp


async def main():
    print("NP bot starting (standalone)...")
    await np_dp.start_polling(np_bot)


if __name__ == "__main__":
    asyncio.run(main())
