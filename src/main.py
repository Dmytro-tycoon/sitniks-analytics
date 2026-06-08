import asyncio
from src.telegram_bot.bot import bot, dp
from src.telegram_bot.ads_bot import ads_bot, ads_dp
from src.scheduler.jobs import setup_scheduler
from src.webhook_server import run_web
from src.config import settings


async def main():
    scheduler = setup_scheduler()
    scheduler.start()
    job = scheduler.get_job("daily_analysis")
    print(f"Scheduler started. Next daily analysis: {job.next_run_time}")
    ads_job = scheduler.get_job("daily_ads_report")
    if ads_job:
        print(f"Next daily ads report: {ads_job.next_run_time}")

    # Web-сервер для Sitniks webhooks (в фоні)
    asyncio.create_task(run_web())

    # Запускаємо два боти паралельно
    print("Telegram bots starting...")
    tasks = [dp.start_polling(bot)]
    if settings.ADS_BOT_TOKEN:
        tasks.append(ads_dp.start_polling(ads_bot))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
