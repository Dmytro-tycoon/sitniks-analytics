"""
Аналітика рекламних постів: який пост → скільки замовлень.

Логіка:
  Order.chatId → перше повідомлення чату → adInfo.adTitle
"""
import asyncio
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Tuple

from src.sitniks.client import SitniksClient


NO_AD_LABEL = "Без реклами (прямі)"


async def _resolve_ad_titles(orders: List[Dict], sitniks: SitniksClient) -> List[Tuple[Dict, str]]:
    """Для кожного замовлення повертає (order, ad_title)."""
    sem = asyncio.Semaphore(3)

    async def fetch_one(order: Dict) -> Tuple[Dict, str]:
        chat_id = order.get("chatId")
        if not chat_id:
            return order, NO_AD_LABEL
        order_created = order.get("createdAt") or ""
        async with sem:
            ad = await sitniks.get_ad_info_for_chat(chat_id, before_iso=order_created)
            await asyncio.sleep(0.1)
        return order, (ad["adTitle"].strip() if ad else NO_AD_LABEL)

    return await asyncio.gather(*[fetch_one(o) for o in orders])


async def build_ad_report(date_from: datetime, date_to: datetime,
                          exclude_reported: bool = False) -> Dict:
    """
    Завантажує замовлення за період і повертає звіт.

    exclude_reported=True → відсіює замовлення, які вже були в попередніх ads-звітах
    (для cron-job, щоб не дублювати).
    Повертає: {date, stats, total, orders_resolved, skipped_already_reported}
    """
    sitniks = SitniksClient()
    try:
        orders = await sitniks.get_orders(date_from, date_to)
        resolved = await _resolve_ad_titles(orders, sitniks)
    finally:
        await sitniks.close()

    skipped = 0
    if exclude_reported:
        from src.database.supabase_client import get_reported_order_ids
        already = get_reported_order_ids()
        before = len(resolved)
        resolved = [(o, t) for (o, t) in resolved if o.get("id") not in already]
        skipped = before - len(resolved)

    counts: Dict[str, int] = defaultdict(int)
    for _, title in resolved:
        counts[title] += 1

    return {
        "date": date_from.strftime("%d.%m.%Y"),
        "stats": dict(counts),
        "total": sum(counts.values()),
        "orders_resolved": resolved,
        "skipped_already_reported": skipped,
    }


def mark_report_as_sent(report: Dict):
    """Записує всі замовлення зі звіту в reported_ad_orders."""
    from src.database.supabase_client import mark_orders_reported
    rows = []
    for order, title in report.get("orders_resolved", []):
        oid = order.get("id")
        if not oid:
            continue
        rows.append({
            "order_id": oid,
            "ad_title": title,
            "order_date": (order.get("createdAt") or "")[:10] or None,
            "chat_id": order.get("chatId"),
        })
    if rows:
        mark_orders_reported(rows)
    return len(rows)


def format_ad_report(report: Dict) -> str:
    """Форматує звіт для Telegram (HTML)."""
    stats = report["stats"]
    total = report["total"]
    date = report["date"]

    if not stats:
        return f"📊 За {date} замовлень не знайдено."

    # Сортуємо за кількістю
    sorted_items = sorted(stats.items(), key=lambda x: x[1], reverse=True)

    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"📣 <b>Замовлення по рекламних постах за {date}</b>",
        f"Всього замовлень: <b>{total}</b>",
    ]
    skipped = report.get("skipped_already_reported", 0)
    if skipped:
        lines.append(f"<i>(пропущено {skipped} вже надісланих раніше)</i>")
    lines.append("")

    for i, (title, count) in enumerate(sorted_items):
        icon = medals[i] if i < len(medals) else "▪️"
        pct = round(count / total * 100) if total else 0
        lines.append(f"{icon} {title}")
        lines.append(f"   → <b>{count}</b> замовлень ({pct}%)")

    return "\n".join(lines)
