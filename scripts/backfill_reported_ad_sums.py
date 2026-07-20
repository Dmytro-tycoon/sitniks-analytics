"""
ОПЦІЙНИЙ backfill: для всіх записів у reported_ad_orders, де sum_uah IS NULL,
підтягнути суму замовлення (totalPriceDiscount) з Sitniks.

УВАГА: is_stale лишається False для історичних рядків (перерахунок дорогий).
Якщо потім refill'ити старий день у sheet — сума "Без реклами" буде НИЖЧА,
ніж було при першому запису (Стара атрибуція не додасться). Тому цей скрипт
використовуйте, тільки якщо збираєтесь перегенерувати таблицю з нуля.

Використання:
  python scripts/backfill_reported_ad_sums.py [days_back=60]
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import pytz

from src.database.supabase_client import get_client
from src.sitniks.client import SitniksClient
from src.analyzer.ad_analytics import _is_stale

KIEV = pytz.timezone("Europe/Kiev")


async def backfill(days_back: int = 60):
    # Читаємо unfilled рядки
    res = get_client().table("reported_ad_orders") \
        .select("order_id, order_date, chat_id, ad_title") \
        .is_("sum_uah", "null") \
        .execute()
    rows = res.data or []
    if not rows:
        print("Немає рядків для backfill'у.")
        return

    # Групуємо по датах
    dates = sorted({r["order_date"] for r in rows if r.get("order_date")})
    print(f"{len(rows)} рядків без sum_uah, за {len(dates)} дат: {dates[:5]}...")

    sitniks = SitniksClient()
    updated = 0
    for d in dates:
        date_from = KIEV.localize(datetime.fromisoformat(d).replace(hour=0, minute=0))
        date_to = date_from + timedelta(days=1)
        try:
            orders = await sitniks.get_orders(date_from, date_to)
        except Exception as e:
            print(f"  {d}: FAILED {e}")
            continue

        by_id = {o["id"]: o for o in orders}
        day_rows = [r for r in rows if r["order_date"] == d]

        # Для is_stale: беремо adInfo найсвіжіший до order.createdAt для того chat_id
        for r in day_rows:
            o = by_id.get(r["order_id"])
            if not o:
                continue
            amount = o.get("totalPriceDiscount")
            if amount is None:
                amount = o.get("totalPrice") or 0
            # is_stale: перевіряємо adInfo
            cid = r.get("chat_id")
            ad_created = None
            if cid:
                try:
                    ad = await sitniks.get_ad_info_for_chat(cid, before_iso=o.get("createdAt"))
                    if ad:
                        # хочемо createdAt повідомлення з adInfo, а не самого оголошення
                        # у поточному API це "adCreatedAt" відсутнє — використовуємо
                        # логіку через messages: пропущено, is_stale лишається False
                        pass
                except Exception:
                    pass
            get_client().table("reported_ad_orders") \
                .update({"sum_uah": float(amount or 0)}) \
                .eq("order_id", r["order_id"]) \
                .execute()
            updated += 1
        print(f"  {d}: оновлено {len(day_rows)} рядків")

    await sitniks.close()
    print(f"\nВсього оновлено: {updated}")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    asyncio.run(backfill(days))
