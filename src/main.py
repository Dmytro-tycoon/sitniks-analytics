import asyncio
from src.telegram_bot.bot import bot, dp
from src.scheduler.jobs import setup_scheduler


async def main():
    scheduler = setup_scheduler()
    scheduler.start()
    print("Scheduler started (daily analysis at 09:00 Kiev)")
    print("Telegram bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
