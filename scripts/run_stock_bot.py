"""Локальний запуск ЛИШЕ бота закупівель (для тесту, без інших ботів).

    source venv/bin/activate
    PYTHONPATH=. python scripts/run_stock_bot.py
"""
import asyncio
from src.telegram_bot.stock_bot import stock_bot, stock_dp


async def main():
    print("Stock bot polling started. Ctrl+C to stop.")
    await stock_dp.start_polling(stock_bot)


if __name__ == "__main__":
    asyncio.run(main())
