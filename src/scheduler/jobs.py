from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import pytz

from src.analyzer.pipeline import analyze_period
from src.telegram_bot.bot import send_daily_reports
from src.telegram_bot.ads_bot import send_daily_ads_report, reattribute_yesterday
from src.analyzer.stats_pipeline import run_stats_for_date
from src.sheets.client import SheetsClient
from src.config import settings

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


async def daily_hair_stats_job():
    """Щоранку о 07:00: збір статистики skin.one.hair → Google Sheets"""
    from datetime import date, timedelta
    yesterday = date.today() - timedelta(days=1)
    print(f"[{datetime.now()}] daily_hair_stats_job started for {yesterday}")
    try:
        sheets = SheetsClient(
            service_account_file=settings.GOOGLE_SERVICE_ACCOUNT_FILE,
            spreadsheet_id=settings.HAIR_STATS_SPREADSHEET_ID,
        )
        await run_stats_for_date(
            target_date=yesterday,
            fb_token=settings.FB_ACCESS_TOKEN,
            sheets=sheets,
        )
        print(f"[{datetime.now()}] daily_hair_stats_job done")
    except Exception as e:
        print(f"[{datetime.now()}] daily_hair_stats_job FAILED: {e}")


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=KIEV_TZ)
    scheduler.add_job(
        daily_analysis_job,
        CronTrigger(hour=6, minute=0, timezone=KIEV_TZ),
        id="daily_analysis",
        replace_existing=True,
    )
    scheduler.add_job(
        send_daily_ads_report,
        CronTrigger(hour=8, minute=30, timezone=KIEV_TZ),
        id="daily_ads_report",
        replace_existing=True,
    )
    scheduler.add_job(
        reattribute_yesterday,
        CronTrigger(hour=22, minute=0, timezone=KIEV_TZ),
        id="daily_ads_reattribution",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_hair_stats_job,
        CronTrigger(hour=5, minute=30, timezone=KIEV_TZ),
        id="daily_hair_stats",
        replace_existing=True,
    )
    return scheduler
