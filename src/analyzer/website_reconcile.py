"""
Звірка замовлень із сайту (website_orders) з Sitniks.

Логіка:
  Для кожної заявки з сайту шукаємо в Sitniks замовлення того ж клієнта
  (по нормалізованому телефону) за день заявки + наступний день.

  Якщо знайдено → sitniks_order_id + confirmed_uah = totalPriceDiscount.
  Якщо після наступного дня (тобто вікно закрито) матчу нема → confirmed_uah = 0.
"""
import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional, Dict, List

import pytz

from src.sitniks.client import SitniksClient
from src.database.supabase_client import get_client

logger = logging.getLogger(__name__)
KIEV_TZ = pytz.timezone("Europe/Kiev")


def _normalize_phone(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    digits = re.sub(r"\D", "", p)
    return digits[-10:] if len(digits) >= 10 else None


async def reconcile_date(target_date: date) -> Dict:
    """
    Звіряє заявки за target_date з Sitniks-замовленнями за target_date і +1 день.

    Оновлює website_orders:
      - sitniks_order_id (якщо знайдено)
      - confirmed_uah (з totalPriceDiscount)
      - reconciled_at

    Якщо вікно вже закрилось (сьогодні > target_date + 1) і матчу нема →
    confirmed_uah = 0 (заявка не сконвертувалась).
    """
    sb = get_client()
    res = sb.table("website_orders") \
        .select("order_id, client_phone, order_date, total_uah, sitniks_order_id") \
        .eq("order_date", target_date.isoformat()) \
        .execute()
    site_rows = res.data or []
    if not site_rows:
        return {"date": target_date.isoformat(), "site_orders": 0, "matched": 0}

    # Тягнемо Sitniks-замовлення за вікно
    date_from = KIEV_TZ.localize(datetime(target_date.year, target_date.month, target_date.day))
    date_to = date_from + timedelta(days=2)  # включно з наступним днем

    sitniks = SitniksClient()
    try:
        sitniks_orders = await sitniks.get_orders(date_from, date_to)
    finally:
        await sitniks.close()

    # Побудова індексу по телефону (беремо MIN totalPriceDiscount по кожному phone,
    # якщо у клієнта декілька — вибираємо перше за часом)
    phone_index: Dict[str, Dict] = {}
    for o in sitniks_orders:
        c = o.get("client") or {}
        ph = _normalize_phone(c.get("phone"))
        if not ph:
            continue
        # Беремо перше замовлення (за часом) на телефон — щоб не сплутати повторні
        if ph not in phone_index or (o.get("createdAt") or "") < (phone_index[ph].get("createdAt") or ""):
            phone_index[ph] = o

    # Матчимо
    today = datetime.now(KIEV_TZ).date()
    window_closed = today > (target_date + timedelta(days=1))

    now_iso = datetime.now(pytz.utc).isoformat()
    updates_matched = 0
    updates_no_match = 0

    for row in site_rows:
        ph = _normalize_phone(row.get("client_phone"))
        if not ph:
            continue
        o = phone_index.get(ph)
        if o:
            amount = o.get("totalPriceDiscount")
            if amount is None:
                amount = o.get("totalPrice") or 0
            sb.table("website_orders").update({
                "sitniks_order_id": o.get("id"),
                "confirmed_uah": float(amount or 0),
                "reconciled_at": now_iso,
            }).eq("order_id", row["order_id"]).execute()
            updates_matched += 1
        elif window_closed:
            # Матчу нема і вікно закрито → заявка не сконвертувалась
            sb.table("website_orders").update({
                "confirmed_uah": 0,
                "reconciled_at": now_iso,
            }).eq("order_id", row["order_id"]).execute()
            updates_no_match += 1
        # inакше — pending, чекаємо наступного дня

    return {
        "date": target_date.isoformat(),
        "site_orders": len(site_rows),
        "matched": updates_matched,
        "not_converted": updates_no_match,
        "still_pending": len(site_rows) - updates_matched - updates_no_match,
    }


async def reconcile_last_two_days() -> List[Dict]:
    """Викликається з cron о 21:00: звіряє сьогодні і вчора."""
    today = datetime.now(KIEV_TZ).date()
    yesterday = today - timedelta(days=1)

    results = []
    for d in [yesterday, today]:
        r = await reconcile_date(d)
        print(f"[reconcile] {r}")
        results.append(r)
    return results
