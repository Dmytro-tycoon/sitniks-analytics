"""
Аналітика рекламних постів: який пост → скільки замовлень.

Логіка:
  Order.chatId → перше повідомлення чату → adInfo.adTitle
"""
import asyncio
from collections import defaultdict
from datetime import datetime
from typing import List, Dict

from src.sitniks.client import SitniksClient


NO_AD_LABEL = "Без реклами (прямі)"


async def get_ad_stats_for_orders(orders: List[Dict], sitniks: SitniksClient) -> Dict[str, int]:
    """
    Для списку замовлень повертає словник {ad_title: кількість_замовлень}.
    Замовлення без chatId або без adInfo → NO_AD_LABEL.
    """
    counts: Dict[str, int] = defaultdict(int)
    sem = asyncio.Semaphore(3)

    async def fetch_one(order: Dict):
        chat_id = order.get("chatId")
        if not chat_id:
            return NO_AD_LABEL
        async with sem:
            ad = await sitniks.get_ad_info_for_chat(chat_id)
            await asyncio.sleep(0.1)
        return ad["adTitle"].strip() if ad else NO_AD_LABEL

    titles = await asyncio.gather(*[fetch_one(o) for o in orders])
    for t in titles:
        counts[t] += 1

    return dict(counts)


async def build_ad_report(date_from: datetime, date_to: datetime) -> Dict:
    """
    Завантажує замовлення за період і повертає готовий звіт.
    Повертає: {"date": str, "stats": {ad_title: count}, "total": int}
    """
    sitniks = SitniksClient()
    try:
        orders = await sitniks.get_orders(date_from, date_to)
        stats = await get_ad_stats_for_orders(orders, sitniks)
    finally:
        await sitniks.close()

    return {
        "date": date_from.strftime("%d.%m.%Y"),
        "stats": stats,
        "total": sum(stats.values()),
    }


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
        "",
    ]

    for i, (title, count) in enumerate(sorted_items):
        icon = medals[i] if i < len(medals) else "▪️"
        pct = round(count / total * 100) if total else 0
        lines.append(f"{icon} {title}")
        lines.append(f"   → <b>{count}</b> замовлень ({pct}%)")

    return "\n".join(lines)
