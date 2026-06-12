"""
Разова заливка даних Instagram-промоцій у Google Sheets.

Розподіляє суми рівномірно по днях May 13 – Jun 11 (30 днів),
ДОДАЮЧИ до вже існуючих даних (Facebook Ads).

Використання:
    python scripts/backfill_instagram.py
"""
import sys
import logging
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
from src.sheets.client import SheetsClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── Загальні дані Instagram-промоцій (з скрінів) ──────────────────────────
INSTAGRAM_TOTAL = {
    "spend":       13_033.81,  # ₴ — сума витрат по всіх об'явах
    "impressions": 108_345,    # переглядів разом
    "clicks":      2_008,      # відвідувань профілю разом
}

PERIOD_START = date(2026, 5, 13)
PERIOD_END   = date(2026, 6, 11)  # включно

# ── Розрахунок денних середніх ─────────────────────────────────────────────
days = (PERIOD_END - PERIOD_START).days + 1  # = 30

DAILY = {
    "spend":       round(INSTAGRAM_TOTAL["spend"] / days, 2),
    "impressions": round(INSTAGRAM_TOTAL["impressions"] / days),
    "clicks":      round(INSTAGRAM_TOTAL["clicks"] / days),
}

print(f"\n📊 Instagram-промоції: {PERIOD_START} → {PERIOD_END} ({days} днів)")
print(f"  Щоденно додаємо:")
print(f"    Витрати:    {DAILY['spend']:.2f} ₴")
print(f"    Перегляди:  {DAILY['impressions']}")
print(f"    Кліки:      {DAILY['clicks']}")
print()


def add_instagram_to_day(sheets: SheetsClient, target_date: date):
    """Читає поточні значення клітинок і додає Instagram-дані."""
    month = target_date.month
    day = target_date.day
    sheet = sheets._sheet_name(month)
    col = sheets._get_day_column(month, day)
    if not col:
        logger.warning(f"  ⚠️  Не знайдено колонку для {target_date}")
        return

    from src.sheets.client import LOWER_TABLE_ROWS
    rows_to_update = {
        "fb_spend":       LOWER_TABLE_ROWS["fb_spend"],
        "fb_impressions": LOWER_TABLE_ROWS["fb_impressions"],
        "fb_clicks":      LOWER_TABLE_ROWS["fb_clicks"],
    }

    # Читаємо поточні значення (UNFORMATTED — без "грн.", "$" тощо)
    ranges = [f"'{sheet}'!{col}{row}" for row in rows_to_update.values()]
    result = sheets._service.spreadsheets().values().batchGet(
        spreadsheetId=sheets.spreadsheet_id,
        ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute()

    value_ranges = result.get("valueRanges", [])

    def parse_val(vr):
        try:
            raw = vr.get("values", [[0]])[0][0]
            return float(str(raw).replace(",", ".").replace(" ", "")) if raw else 0.0
        except Exception:
            return 0.0

    current_spend       = parse_val(value_ranges[0])
    current_impressions = parse_val(value_ranges[1])
    current_clicks      = parse_val(value_ranges[2])

    new_spend       = round(current_spend + DAILY["spend"], 2)
    new_impressions = int(current_impressions + DAILY["impressions"])
    new_clicks      = int(current_clicks + DAILY["clicks"])

    data = [
        {"range": f"'{sheet}'!{col}{rows_to_update['fb_spend']}",       "values": [[new_spend]]},
        {"range": f"'{sheet}'!{col}{rows_to_update['fb_impressions']}", "values": [[new_impressions]]},
        {"range": f"'{sheet}'!{col}{rows_to_update['fb_clicks']}",      "values": [[new_clicks]]},
    ]
    sheets._service.spreadsheets().values().batchUpdate(
        spreadsheetId=sheets.spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()

    logger.info(
        f"  ✅ {target_date}: витрати {current_spend:.0f}→{new_spend:.0f} ₴, "
        f"перегляди {current_impressions:.0f}→{new_impressions}, "
        f"кліки {current_clicks:.0f}→{new_clicks}"
    )


def main():
    sheets = SheetsClient(
        service_account_file=settings.GOOGLE_SERVICE_ACCOUNT_FILE,
        spreadsheet_id=settings.HAIR_STATS_SPREADSHEET_ID,
    )

    current = PERIOD_START
    while current <= PERIOD_END:
        add_instagram_to_day(sheets, current)
        current += timedelta(days=1)

    print(f"\n✅ Готово! Оброблено {days} днів.")


if __name__ == "__main__":
    main()
