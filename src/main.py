import asyncio
from src.telegram_bot.bot import bot, dp
from src.scheduler.jobs import setup_scheduler


async def main():
    scheduler = setup_scheduler()
    scheduler.start()
    # Виводимо коли реально стрельне наступний раз
    job = scheduler.get_job("daily_analysis")
    print(f"Scheduler started. Next daily analysis: {job.next_run_time}")
    print("Telegram bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
