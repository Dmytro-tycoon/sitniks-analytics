"""Розвідка + топ-10 товарів за N днів (швидкість продажів).

Запуск:
    source venv/bin/activate
    PYTHONPATH=. python scripts/explore_orders.py [days]
"""
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from src.sitniks.client import SitniksClient


async def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    client = SitniksClient()
    date_to = datetime.now()
    date_from = date_to - timedelta(days=days)

    orders = await client.get_orders(date_from, date_to)
    print(f"Замовлень за {days} днів: {len(orders)}\n")

    # 1. Розподіл статусів
    status_counter = Counter()
    for o in orders:
        st = o.get("status")
        # статус може бути dict {id,title} або рядок
        label = st.get("title") if isinstance(st, dict) else st
        status_counter[str(label)] += 1
    print("=== СТАТУСИ ЗАМОВЛЕНЬ ===")
    for label, cnt in status_counter.most_common():
        print(f"  {cnt:>5}  {label}")
    print()

    # 2. Агрегація по SKU (кількість проданого)
    qty_by_sku = defaultdict(float)
    title_by_sku = {}
    for o in orders:
        for p in o.get("products", []) or []:
            var = p.get("productVariation") or {}
            sku = var.get("sku") or f"pid-{var.get('productId')}"
            qty = float(p.get("quantity") or 0)
            qty_by_sku[sku] += qty
            if sku not in title_by_sku:
                # коротка назва
                t = (var.get("systemTitle") or p.get("title") or "").split(" Об'єм")[0]
                title_by_sku[sku] = t[:55]

    top = sorted(qty_by_sku.items(), key=lambda kv: -kv[1])[:10]

    print(f"=== ТОП-10 ТОВАРІВ за {days} днів ===")
    print(f"{'SKU':<10}{'Продано':>9}{'/тиждень':>10}{'/день':>8}  Назва")
    for sku, total in top:
        per_week = total / (days / 7)
        per_day = total / days
        print(f"{sku:<10}{total:>9.0f}{per_week:>10.1f}{per_day:>8.2f}  {title_by_sku.get(sku,'')}")


if __name__ == "__main__":
    asyncio.run(main())
