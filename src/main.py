import asyncio
from src.telegram_bot.bot import bot, dp
from src.telegram_bot.ads_bot import ads_bot, ads_dp
from src.telegram_bot.np_bot import np_bot, np_dp
from src.scheduler.jobs import setup_scheduler
from src.webhook_server import run_web
from src.config import settings


async def main():
    scheduler = setup_scheduler()
    scheduler.start()
    print("Scheduler started. Jobs:")
    for j in sorted(scheduler.get_jobs(), key=lambda x: x.id):
        print(f"  - {j.id}: next {j.next_run_time}")

    # Web-сервер для Sitniks webhooks (в фоні)
    asyncio.create_task(run_web())

    # Запускаємо боти паралельно
    print("Telegram bots starting...")
    tasks = [dp.start_polling(bot)]
    if settings.ADS_BOT_TOKEN:
        tasks.append(ads_dp.start_polling(ads_bot))
    if settings.NP_BOT_TOKEN:
        tasks.append(np_dp.start_polling(np_bot))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
