from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import pytz

from src.analyzer.pipeline import analyze_period
from src.telegram_bot.bot import send_daily_reports
from src.telegram_bot.ads_bot import send_daily_ads_report, reattribute_yesterday
from src.analyzer.stats_pipeline import run_stats_for_date
from src.sheets.client import SheetsClient
from src.sheets.ads_sums import write_daily_sums_to_sheet
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


async def daily_ads_sheet_job():
    """Щоранку о 08:45 Київ: пише суми по рекламних постах у Google Sheets."""
    print(f"[{datetime.now()}] daily_ads_sheet_job started")
    try:
        result = await write_daily_sums_to_sheet()
        print(f"[{datetime.now()}] daily_ads_sheet_job done: {result}")
    except Exception as e:
        print(f"[{datetime.now()}] daily_ads_sheet_job FAILED: {e}")


async def daily_hair_stats_job():
    """Щоранку о 05:30 Київ: збір статистики skin.one.hair → Google Sheets.

    Розраховує "вчорашній день" за Києвом (не за UTC),
    щоб уникнути плутанини при пуску близько до півночі.
    """
    from datetime import timedelta
    yesterday = (datetime.now(KIEV_TZ) - timedelta(days=1)).date()
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
        # run_stats_for_date уже шле Telegram-сповіщення про помилку
        print(f"[{datetime.now()}] daily_hair_stats_job FAILED: {e}")


async def scheduler_heartbeat():
    """Друкує серцебиття кожні 30 хвилин — щоб бачити чи планувальник живий."""
    print(f"[{datetime.now(KIEV_TZ).isoformat()}] scheduler heartbeat")


def setup_scheduler() -> AsyncIOScheduler:
    # job_defaults: якщо job не запустився вчасно (deploy/restart) —
    # apscheduler наздожене протягом 12 годин (misfire_grace_time=43200).
    # Це важливо, бо на Railway event loop інколи "провисає" на кілька годин
    # через паралельні Telegram polling-и, і job би пропускався зовсім.
    # coalesce=True: якщо пропущено кілька запусків — зробити лише один.
    job_defaults = {
        "misfire_grace_time": 12 * 60 * 60,
        "coalesce": True,
    }
    scheduler = AsyncIOScheduler(timezone=KIEV_TZ, job_defaults=job_defaults)
    scheduler.add_job(
        daily_analysis_job,
        CronTrigger(hour=5, minute=30, timezone=KIEV_TZ),
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
    # daily_ads_sheet_job більше НЕ окремим cron — write_daily_sums_to_sheet
    # тепер викликається інлайн наприкінці send_daily_ads_report (08:30),
    # щоб уникнути конкуренції за Sitniks API rate-limit.
    # Heartbeat: пише в лог кожні 30 хв — щоб бачити чи планувальник живий
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.add_job(
        scheduler_heartbeat,
        IntervalTrigger(minutes=30),
        id="heartbeat",
        replace_existing=True,
    )
    return scheduler
