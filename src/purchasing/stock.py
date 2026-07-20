"""MVP закупу: скільки має бути на складі по ключових товарах.

Дві категорії товарів:
  • РОЗПИВ — один засіб продається в різному мілілітражі з одного бульку.
    Рахуємо СУМАРНІ мілілітри: Σ(продано × мл) → мл/день → × горизонт.
  • ОКРЕМІ ПАКУВАННЯ (О-П) — заводське пакування, рахуємо в ШТУКАХ.

Формула (для обох): середній продаж/день × горизонт покриття (днів).
Горизонт = 30 днів, без страхового буфера (узгоджено 16.07.2026).

Джерело — Sitniks /orders (поле `products`). Скасовані замовлення
(статус «Відмінено») з попиту виключаються.
"""
import math
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict

from src.sitniks.client import SitniksClient

# --- Параметри ---
DEFAULT_WINDOW_DAYS = 90      # період для оцінки швидкості продажів
DEFAULT_COVERAGE_DAYS = 30    # на скільки днів має вистачати запасу
DEFAULT_SAFETY = 0.0          # страховий буфер (0.2 = +20%)

EXCLUDED_STATUSES = {"відмінено", "скасовано", "повернення"}

# --- РОЗПИВ: об'єднані ml-групи. Ключ SKU → мілілітраж однієї одиниці ---
BULK_GROUPS: Dict[str, Dict] = {
    "U-12": {"name": "Крем для очей Bio Renaturation",
             "members": {"U-12-5": 5, "U-12-10": 10}},
    "U-5":  {"name": "Крем регенерація Bio Renaturation",
             "members": {"U-5-10": 10, "U-5-20": 20}},
    "U-23": {"name": "Крем з вітаміном К USOLAB",
             "members": {"U-23-10": 10, "U-23-20": 20}},
    "AG-1": {"name": "Зволожуючий крем SPF 50+",
             "members": {"AG-1-10": 10, "AG-1-20": 20, "AG-1-30": 30, "AG-1-50": 50}},
}

# --- ОКРЕМІ ПАКУВАННЯ: рахуємо в штуках. (повна назва, варіант пакування) ---
UNIT_SKUS: Dict[str, Dict] = {
    "U-12-30":   {"name": "Крем для очей Bio Renaturation", "variant": "30 мл (О-П)"},
    "U-5-50":    {"name": "Крем регенерація Bio Renaturation", "variant": "50 мл"},
    "U-5-100":   {"name": "Крем регенерація Bio Renaturation", "variant": "100 мл"},
    "U-23-15":   {"name": "Крем з вітаміном К USOLAB", "variant": "15 мл (О-П)"},
    "U-23-50":   {"name": "Крем з вітаміном К USOLAB", "variant": "50 мл (О-П)"},
    "AG-1-50OP": {"name": "Зволожуючий крем SPF 50+", "variant": "50 мл (О-П)"},
}

IGNORE_SKUS = {"U-12-31"}


def _status_label(order: dict) -> str:
    st = order.get("status")
    label = st.get("title") if isinstance(st, dict) else st
    return str(label or "").strip().lower()


async def compute_recommended_stock(
    window_days: int = DEFAULT_WINDOW_DAYS,
    coverage_days: int = DEFAULT_COVERAGE_DAYS,
    safety: float = DEFAULT_SAFETY,
) -> List[Dict]:
    """Повертає рядки рекомендованого запасу.

    Кожен рядок: key, label, unit ('мл'|'шт'), sold, per_day, per_week, recommended.
    Спочатку розпив (мл), потім окремі пакування (шт) — усі за спаданням recommended.
    """
    client = SitniksClient()
    date_to = datetime.now()
    date_from = date_to - timedelta(days=window_days)
    orders = await client.get_orders(date_from, date_to)

    qty_by_sku = defaultdict(float)
    for order in orders:
        if _status_label(order) in EXCLUDED_STATUSES:
            continue
        for product in order.get("products", []) or []:
            var = product.get("productVariation") or {}
            sku = var.get("sku")
            if sku:
                qty_by_sku[sku] += float(product.get("quantity") or 0)

    factor = coverage_days * (1 + safety)

    bulk_rows, unit_rows = [], []

    # Розпив → сумарні мілілітри
    for key, group in BULK_GROUPS.items():
        total_ml = sum(qty_by_sku.get(sku, 0) * ml for sku, ml in group["members"].items())
        per_day = total_ml / window_days
        bulk_rows.append({
            "key": key,
            "name": group["name"],
            "unit": "мл",
            "sold": round(total_ml),
            "per_day": round(per_day, 1),
            "per_week": round(per_day * 7),
            "recommended": math.ceil(per_day * factor),
        })

    # Окремі пакування → штуки
    for sku, info in UNIT_SKUS.items():
        total = qty_by_sku.get(sku, 0)
        per_day = total / window_days
        unit_rows.append({
            "key": sku,
            "name": f"{info['name']}, {info['variant']}",
            "unit": "шт",
            "sold": int(total),
            "per_day": round(per_day, 2),
            "per_week": round(per_day * 7, 1),
            "recommended": math.ceil(per_day * factor),
        })

    bulk_rows.sort(key=lambda r: -r["recommended"])
    unit_rows.sort(key=lambda r: -r["recommended"])
    return bulk_rows + unit_rows


def format_stock_report(
    rows: List[Dict],
    coverage_days: int = DEFAULT_COVERAGE_DAYS,
    window_days: int = DEFAULT_WINDOW_DAYS,
    safety: float = DEFAULT_SAFETY,
) -> str:
    """HTML-звіт для Telegram."""
    if not rows:
        return "Немає даних по продажах за обраний період."

    buf = f" +{int(safety * 100)}%" if safety else ""
    bulk = [r for r in rows if r["unit"] == "мл"]
    units = [r for r in rows if r["unit"] == "шт"]

    out = [
        f"📦 <b>Рекомендований залишок</b>",
        f"<i>покриття {coverage_days} дн{buf} · швидкість за {window_days} дн</i>",
    ]

    if bulk:
        out += ["", "🧴 <b>Розпив</b> (мілілітри)"]
        for r in bulk:
            out.append(
                f"\n<b>{r['name']}</b> <code>[{r['key']}]</code>\n"
                f"   {r['per_week']} мл/тижд → має бути <b>{r['recommended']} мл</b>"
            )

    if units:
        out += ["", "📦 <b>Окремі пакування</b> (штуки)"]
        for r in units:
            out.append(
                f"\n<b>{r['name']}</b> <code>[{r['key']}]</code>\n"
                f"   {r['per_week']} шт/тижд → має бути <b>{r['recommended']} шт</b>"
            )

    return "\n".join(out)
