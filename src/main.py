import asyncio
from src.telegram_bot.bot import bot, dp
from src.scheduler.jobs import setup_scheduler
from src.webhook_server import run_web


async def main():
    scheduler = setup_scheduler()
    scheduler.start()
    job = scheduler.get_job("daily_analysis")
    print(f"Scheduler started. Next daily analysis: {job.next_run_time}")

    # Web-сервер для Sitniks webhooks (в фоні)
    asyncio.create_task(run_web())

    print("Telegram bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
