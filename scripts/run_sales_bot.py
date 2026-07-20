"""Запуск агента-продавця в окремому Telegram-боті (пісочниця або бойовий).

    python scripts/run_sales_bot.py

Потрібен TELEGRAM_SALES_BOT_TOKEN у .env (окремий бот від @BotFather).
Напиши боту — і поспілкуйся з агентом, як клієнт.
"""
import asyncio

from src.consultant.channels.telegram_sales import run

if __name__ == "__main__":
    asyncio.run(run())
