"""Ручний тест аналітики рекламних постів."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.analyzer.ad_analytics import build_ad_report, format_ad_report


async def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    date_to = datetime.now()
    date_from = date_to - timedelta(days=days_back)

    print(f"Аналізую замовлення за {date_from.date()} — {date_to.date()}...\n")
    report = await build_ad_report(date_from, date_to)

    print(f"Знайдено {report['total']} замовлень\n")
    for title, count in sorted(report["stats"].items(), key=lambda x: -x[1]):
        print(f"  {count:3d}  {title}")

    print("\n--- Telegram-формат ---")
    print(format_ad_report(report))


asyncio.run(main())
