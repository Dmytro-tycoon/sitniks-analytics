"""
Ручний запуск збору статистики для skin.one.hair → Google Sheets.

Використання:
    python scripts/run_stats_report.py           # вчора
    python scripts/run_stats_report.py 2026-06-11  # конкретна дата
"""
import asyncio
import sys
import logging
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.sitniks.client import SitniksClient
from src.sheets.client import SheetsClient
from src.analyzer.stats_pipeline import run_stats_for_date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def main():
    if len(sys.argv) > 1:
        target_date = date.fromisoformat(sys.argv[1])
    else:
        target_date = date.today() - timedelta(days=1)  # вчора

    logger.info(f"📊 Збираємо статистику за {target_date} (skin.one.hair)")

    sitniks = SitniksClient()
    sheets = SheetsClient(
        service_account_file=settings.GOOGLE_SERVICE_ACCOUNT_FILE,
        spreadsheet_id=settings.HAIR_STATS_SPREADSHEET_ID,
    )

    stats = await run_stats_for_date(
        target_date=target_date,
        sitniks=sitniks,
        fb_token=settings.FB_ACCESS_TOKEN,
        sheets=sheets,
    )

    print("\n📋 Результат:")
    print(f"  ТО:                {stats['to']:.2f} грн")
    print(f"  Маржа:             {stats['margin']:.2f} грн")
    print(f"  Заявок:            {stats['leads']}")
    print(f"  Продажів всього:   {stats['sales_total']}")
    print(f"  Повторних:         {stats['sales_repeat']}")
    print(f"  FB бюджет:         {stats['fb_spend']:.2f} грн")
    print(f"  FB показів:        {stats['fb_impressions']}")
    print(f"  FB кліків:         {stats['fb_clicks']}")


if __name__ == "__main__":
    asyncio.run(main())
