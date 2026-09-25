"""
Замовлення з сайту skin-one.com.ua — беремо їх з Sitniks за коментарем.

Sitniks-замовлення, оформлене через сайт, має managerComment типу:
    Сайт skin-one.com.ua. звʼязок: Telegram; Нова Пошта, ... ;
    оплата: ... ; Реклама: meta / skinone_sales_2209 / ... / catalog (fbclid).
    Разом 1 420 грн

Парсимо звідти `Реклама: XXX (fbclid)` як ad_label. Суму беремо з
totalPriceDiscount (реальна оплачена сума з урахуванням змін після оформлення).
"""
import re
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional

import pytz

from src.sitniks.client import SitniksClient

KIEV_TZ = pytz.timezone("Europe/Kiev")

SITE_MARKER = "Сайт skin-one.com.ua"
RE_AD = re.compile(r"Реклама:\s*(.+?)\)", re.I)  # до першої `)` — захоплює "...(fbclid" без завершальної


def _extract_ad_label(comment: str) -> Optional[str]:
    """Витягує `Реклама: ...` з коментаря, повертає з "(fbclid)"."""
    if not comment:
        return None
    m = RE_AD.search(comment)
    if not m:
        return None
    # Group captures "meta / ... / catalog (fbclid" — додаємо закриту дужку
    return m.group(1).strip() + ")"


def is_site_order(order: dict) -> bool:
    """True якщо замовлення оформлене через сайт (за коментарем)."""
    return SITE_MARKER in (order.get("managerComment") or "")


# Замовлення зі статусом "Новий" (у Sitniks) — заявка ще не сплачена;
# у наші звіти не потрапляє. Всі інші статуси ("В роботі", "Виконано" тощо)
# означають що менеджер уже підтвердив і почав обробку.
NEW_ORDER_STATUS_TITLE = "Новий"


def is_paid_order(order: dict) -> bool:
    """False для замовлень зі статусом 'Новий' (ще не оплачено)."""
    status_title = ((order.get("status") or {}).get("title") or "").strip()
    return status_title != NEW_ORDER_STATUS_TITLE


def parse_site_order(order: dict) -> Optional[Dict]:
    """
    Повертає dict із розібраними полями сайт-замовлення, або None якщо не сайт
    або якщо статус — 'Новий' (не оплачене).
    """
    if not is_site_order(order):
        return None
    if not is_paid_order(order):
        return None
    comment = order.get("managerComment") or ""
    ad_label = _extract_ad_label(comment) or "Без реклами (прямі)"
    amount = order.get("totalPriceDiscount")
    if amount is None:
        amount = order.get("totalPrice") or 0
    client = order.get("client") or {}
    return {
        "order_id": order.get("id"),
        "created_at": order.get("createdAt"),
        "total_uah": float(amount or 0),
        "ad_label": ad_label,
        "client_name": client.get("fullname"),
        "client_phone": client.get("phone"),
        "status": ((order.get("status") or {}).get("title") or ""),
    }


async def fetch_site_orders_for_date(target_date: date) -> List[Dict]:
    """Всі сайт-замовлення за конкретну дату (Київ)."""
    date_from = KIEV_TZ.localize(datetime(target_date.year, target_date.month, target_date.day))
    date_to = date_from + timedelta(days=1)

    sitniks = SitniksClient()
    try:
        orders = await sitniks.get_orders(date_from, date_to)
    finally:
        await sitniks.close()

    result = []
    for o in orders:
        p = parse_site_order(o)
        if p:
            result.append(p)
    return result


def group_by_ad_label(site_orders: List[Dict]) -> Tuple[Dict[str, float], Dict[str, int]]:
    """Групує сайт-замовлення по ad_label. Повертає (sums, counts)."""
    sums: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for o in site_orders:
        label = o.get("ad_label") or "Без реклами (прямі)"
        sums[label] = sums.get(label, 0) + float(o.get("total_uah") or 0)
        counts[label] = counts.get(label, 0) + 1
    return sums, counts
