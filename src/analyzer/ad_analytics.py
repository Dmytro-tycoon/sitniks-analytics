"""
Аналітика рекламних постів: який пост → скільки замовлень.

Логіка:
  Order.chatId → перше повідомлення чату → adInfo.adTitle
"""
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

from src.sitniks.client import SitniksClient


NO_AD_LABEL = "Без реклами (прямі)"
STALE_AD_DAYS = 30  # реклама вважається "старою", якщо контакт з нею був >30 днів до замовлення


def _iso_to_dt(iso_ts: Optional[str]) -> Optional[datetime]:
    if not iso_ts:
        return None
    try:
        return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except Exception:
        return None


async def _resolve_ad_titles(orders: List[Dict], sitniks: SitniksClient) -> List[Tuple[Dict, str, Optional[str]]]:
    """Для кожного замовлення повертає (order, ad_title, ad_message_created_at)."""
    sem = asyncio.Semaphore(3)

    async def fetch_one(order: Dict) -> Tuple[Dict, str, Optional[str]]:
        chat_id = order.get("chatId")
        if not chat_id:
            return order, NO_AD_LABEL, None
        order_created = order.get("createdAt") or ""
        async with sem:
            ad = await sitniks.get_ad_info_for_chat(chat_id, before_iso=order_created)
            await asyncio.sleep(0.1)
        if not ad:
            return order, NO_AD_LABEL, None
        return order, ad["adTitle"].strip(), ad.get("_messageCreatedAt")

    return await asyncio.gather(*[fetch_one(o) for o in orders])


def _is_stale(order_created: Optional[str], ad_created: Optional[str], days: int = STALE_AD_DAYS) -> bool:
    """True, якщо між моментом adInfo і замовленням > days днів."""
    od = _iso_to_dt(order_created)
    ad_dt = _iso_to_dt(ad_created)
    if not od or not ad_dt:
        return False
    return (od - ad_dt) > timedelta(days=days)


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
        resolved = [(o, t, ac) for (o, t, ac) in resolved if o.get("id") not in already]
        skipped = before - len(resolved)

    counts: Dict[str, int] = defaultdict(int)
    sums: Dict[str, float] = defaultdict(float)
    stale_counts: Dict[str, int] = defaultdict(int)
    stale_sums: Dict[str, float] = defaultdict(float)

    for order, title, ad_created in resolved:
        amount = order.get("totalPriceDiscount")
        if amount is None:
            amount = order.get("totalPrice") or 0
        amount = float(amount or 0)
        if _is_stale(order.get("createdAt"), ad_created):
            stale_counts[title] += 1
            stale_sums[title] += amount
        else:
            counts[title] += 1
            sums[title] += amount

    return {
        "date": date_from.strftime("%d.%m.%Y"),
        "stats": dict(counts),
        "sums": dict(sums),
        "total": sum(counts.values()),
        "total_sum": sum(sums.values()),
        "stale_stats": dict(stale_counts),
        "stale_sums": dict(stale_sums),
        "stale_total": sum(stale_counts.values()),
        "stale_total_sum": sum(stale_sums.values()),
        "orders_resolved": resolved,
        "skipped_already_reported": skipped,
    }


def mark_report_as_sent(report: Dict):
    """Записує всі замовлення зі звіту в reported_ad_orders."""
    from src.database.supabase_client import mark_orders_reported
    rows = []
    for item in report.get("orders_resolved", []):
        # item: (order, title, ad_created)
        order, title = item[0], item[1]
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


def _fmt_uah(amount: float) -> str:
    """1234.5 → '1 234 ₴'  (без копійок, з нерозривним пробілом для розрядів)."""
    return f"{int(round(amount)):,} ₴".replace(",", " ")


def format_ad_report(report: Dict) -> str:
    """Форматує звіт для Telegram (HTML)."""
    stats = report["stats"]
    sums = report.get("sums", {})
    total = report["total"]
    total_sum = report.get("total_sum", 0)
    stale_stats = report.get("stale_stats", {})
    stale_sums = report.get("stale_sums", {})
    stale_total = report.get("stale_total", 0)
    stale_total_sum = report.get("stale_total_sum", 0)
    date = report["date"]

    if not stats and not stale_stats:
        return f"📊 За {date} замовлень не знайдено."

    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"📣 <b>Замовлення по рекламних постах за {date}</b>",
        f"Всього замовлень: <b>{total}</b>  |  на суму <b>{_fmt_uah(total_sum)}</b>",
    ]
    skipped = report.get("skipped_already_reported", 0)
    if skipped:
        lines.append(f"<i>(пропущено {skipped} вже надісланих раніше)</i>")
    lines.append("")

    if stats:
        # Сортуємо за СУМОЮ (від найвигіднішої реклами до найгіршої)
        sorted_items = sorted(stats.items(), key=lambda x: sums.get(x[0], 0), reverse=True)
        for i, (title, count) in enumerate(sorted_items):
            icon = medals[i] if i < len(medals) else "▪️"
            amount = sums.get(title, 0)
            pct = round(amount / total_sum * 100) if total_sum else 0
            lines.append(f"{icon} {title}")
            lines.append(f"   → <b>{count}</b> зам. на <b>{_fmt_uah(amount)}</b> ({pct}%)")

    if stale_stats:
        lines.append("")
        lines.append(f"🕰 <b>Стара атрибуція</b> (контакт з рекламою &gt;{STALE_AD_DAYS} днів)")
        lines.append(f"Всього: <b>{stale_total}</b> зам. на <b>{_fmt_uah(stale_total_sum)}</b>")
        sorted_stale = sorted(stale_stats.items(), key=lambda x: stale_sums.get(x[0], 0), reverse=True)
        for title, count in sorted_stale:
            amount = stale_sums.get(title, 0)
            lines.append(f"▫️ {title}")
            lines.append(f"   → <b>{count}</b> зам. на <b>{_fmt_uah(amount)}</b>")

    return "\n".join(lines)
