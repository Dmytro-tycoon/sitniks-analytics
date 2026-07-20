"""Будує базу знань по товарах для агента-продавця з РЕАЛЬНИХ замовлень Sitniks.

Чому з замовлень: там справжні ціни, реальні об'єми і видно, ЩО реально
купують (популярність) — це заземлює агента, він не вигадує ціни й асортимент.

Виходи:
  clients/skin_one.products.md   — повний каталог (регенерований), групований за
                                    SKU-префіксом, з ціною/об'ємом/популярністю.
  clients/skin_one.products.top.md — компактний топ для промпта (кешований блок).

Запуск:
    source venv/bin/activate
    PYTHONPATH=. python scripts/build_product_kb.py [days] [top_n]
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from src.sitniks.client import SitniksClient

_ROOT = Path(__file__).resolve().parents[1]

# Скасовані/повернені замовлення не рахуємо як «продано».
_BAD_STATUSES = {"Відмінено", "Повернено", "Видалено"}


def _status_label(o: dict) -> str:
    st = o.get("status")
    return (st.get("title") if isinstance(st, dict) else st) or ""


async def _fetch(days: int) -> list[dict]:
    client = SitniksClient()
    try:
        return await client.get_orders(datetime.now() - timedelta(days=days), datetime.now())
    finally:
        await client.close()


def _aggregate(orders: list[dict]) -> dict[str, dict]:
    """SKU → {title, vol, price, qty, orders, upsale}."""
    agg: dict[str, dict] = defaultdict(
        lambda: {"title": "", "vol": "", "price": 0, "qty": 0.0, "orders": 0, "upsale": 0}
    )
    for o in orders:
        if _status_label(o) in _BAD_STATUSES:
            continue
        for p in o.get("products") or []:
            v = p.get("productVariation") or {}
            sku = v.get("sku")
            if not sku:
                continue
            d = agg[sku]
            d["qty"] += float(p.get("quantity") or 0)
            d["orders"] += 1
            # актуальна ціна — з варіації товару (каталожна), fallback на ціну в замовленні
            price = v.get("price") or p.get("price") or 0
            if price:
                d["price"] = int(round(float(price)))
            title = (v.get("systemTitle") or p.get("title") or "").strip()
            # прибираємо хвіст "(sku-...)" з title у замовленні
            if "(sku-" in title:
                title = title.split("(sku-")[0].strip()
            if title:
                d["title"] = title
            vol = ((v.get("product") or {}).get("description") or "").strip()
            if vol:
                d["vol"] = vol
            if p.get("isUpsale"):
                d["upsale"] += 1
    return dict(agg)


def _prefix(sku: str) -> str:
    return sku.split("-")[0]


def _fmt_line(sku: str, d: dict) -> str:
    price = f"{d['price']}₴" if d["price"] else "—"
    vol = f" · {d['vol']}" if d["vol"] else ""
    return f"- `{sku}` — {d['title']}{vol} · **{price}** · продано {int(d['qty'])}"


def build_full(agg: dict[str, dict], days: int) -> str:
    groups: dict[str, list] = defaultdict(list)
    for sku, d in agg.items():
        groups[_prefix(sku)].append((sku, d))
    # групи впорядковуємо за сумарними продажами
    order = sorted(groups.items(), key=lambda kv: -sum(x[1]["qty"] for x in kv[1]))

    out = [
        "# Каталог товарів skin.one (з реальних замовлень)",
        f"> Згенеровано з {sum(d['orders'] for d in agg.values())} позицій замовлень за {days} днів. "
        "Ціни — актуальні каталожні. «продано» — штук за період (популярність).",
        "",
    ]
    for prefix, items in order:
        items.sort(key=lambda x: -x[1]["qty"])
        total = sum(x[1]["qty"] for x in items)
        out.append(f"## Група `{prefix}` ({len(items)} SKU · продано {int(total)})")
        for sku, d in items:
            out.append(_fmt_line(sku, d))
        out.append("")
    return "\n".join(out)


def build_top(agg: dict[str, dict], top_n: int, days: int) -> str:
    top = sorted(agg.items(), key=lambda kv: -kv[1]["qty"])[:top_n]
    out = [
        "# Топ-товари skin.one (найпродаваніші — знай напам'ять)",
        f"> {top_n} найпопулярніших SKU за {days} днів. Ціни реальні. "
        "Якщо клієнт питає товар поза цим списком — уточни в повного каталогу/керівника, НЕ вигадуй ціну.",
        "",
    ]
    for sku, d in top:
        out.append(_fmt_line(sku, d))
    return "\n".join(out)


async def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    orders = await _fetch(days)
    agg = _aggregate(orders)
    print(f"Замовлень: {len(orders)} · унікальних SKU: {len(agg)}")

    full_path = _ROOT / "clients" / "skin_one.products.md"
    top_path = _ROOT / "clients" / "skin_one.products.top.md"
    full_path.write_text(build_full(agg, days), encoding="utf-8")
    top_path.write_text(build_top(agg, top_n, days), encoding="utf-8")
    print(f"✓ {full_path.relative_to(_ROOT)}  ({len(agg)} SKU)")
    print(f"✓ {top_path.relative_to(_ROOT)}  (top {top_n})")


if __name__ == "__main__":
    asyncio.run(main())
