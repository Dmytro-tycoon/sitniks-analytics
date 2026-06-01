from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import pytz

from src.analyzer.pipeline import analyze_period
from src.telegram_bot.bot import send_daily_reports

KIEV_TZ = pytz.timezone("Europe/Kiev")


async def daily_analysis_job():
    """Щоранку: аналіз учорашнього дня + розсилка звітів"""
    print(f"[{datetime.now()}] daily_analysis_job started")
    now = datetime.now(KIEV_TZ)
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        await analyze_period(yesterday_start, today_start)
        await send_daily_reports(yesterday_start.date().isoformat())
        print(f"[{datetime.now()}] daily_analysis_job done")
    except Exception as e:
        print(f"[{datetime.now()}] daily_analysis_job FAILED: {e}")


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=KIEV_TZ)
    scheduler.add_job(
        daily_analysis_job,
        CronTrigger(hour=6, minute=0, timezone=KIEV_TZ),
        id="daily_analysis",
        replace_existing=True,
    )
    return scheduler
