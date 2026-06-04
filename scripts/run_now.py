"""Разовий запуск daily-аналізу за конкретну дату + відправка звіту."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import pytz

KIEV = pytz.timezone("Europe/Kiev")


async def main(target_date: str = None):
    from src.analyzer.pipeline import analyze_period
    from src.telegram_bot.bot import send_daily_reports

    if target_date:
        start = KIEV.localize(datetime.fromisoformat(target_date + "T00:00:00"))
    else:
        now = datetime.now(KIEV)
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    end = start + timedelta(days=1)
    date_str = start.date().isoformat()

    print(f"=== Аналіз за {date_str} ===")
    await analyze_period(start, end)

    print(f"\n=== Надсилання звітів за {date_str} ===")
    await send_daily_reports(date_str)
    print("✅ Готово")


if __name__ == "__main__":
    date = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(main(date))
