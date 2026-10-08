"""
Замовлення з сайту skin-one.com.ua — беремо їх з Sitniks за коментарем.

Sitniks-замовлення, оформлене через сайт, має managerComment типу:
    Сайт skin-one.com.ua. звʼязок: Telegram; Нова Пошта, ... ;
    оплата: ... ; Реклама: meta / skinone_sales_2209 / ... / catalog (fbclid).
    Разом 1 420 грн

Парсимо звідти `Реклама: XXX (fbclid)` як ad_label. Суму беремо з
totalPriceDiscount (реальна оплачена сума з урахуванням змін після оформлення).

Замовлення з Telegram-бота SKIN-ONE Assistant (ним користуються відвідувачі
сайту) теж вважаються сайтовими — за каналом продажу в Sitniks. Даних про
рекламу в них немає, тож вони йдуть окремим рядком BOT_AD_LABEL.
"""
import re
from datetime import datetime, timedelta, date
from typing import Dict, List, Tuple, Optional

import pytz

from src.analyzer.order_status import is_countable_order
from src.sitniks.client import SitniksClient

KIEV_TZ = pytz.timezone("Europe/Kiev")

SITE_MARKER = "Сайт skin-one.com.ua"
BOT_SALES_CHANNEL = "SKIN-ONE Assistant"
BOT_AD_LABEL = "Telegram-бот SKIN-ONE Assistant"
RE_AD = re.compile(r"Реклама:\s*([^\n;]+)", re.I)
CLICK_ID = {"meta": "fbclid", "instagram": "fbclid", "ig": "fbclid", "google": "gclid"}


def _extract_ad_label(comment: str) -> Optional[str]:
    """Витягує `Реклама: ...` з коментаря, повертає з "(fbclid)" / "(gclid)".

    Сайт інколи пише мітку без click-id («Реклама: meta / … / video_duo_face.
    Разом 3 815 грн») — тоді дописуємо його за джерелом, щоб замовлення
    потрапило в той самий рядок, що й мітка з "(fbclid)".
    """
    if not comment:
        return None
    m = RE_AD.search(comment)
    if not m:
        return None
    text = m.group(1)
    if ")" in text:
        return text[:text.index(")") + 1].strip()
    label = re.split(r"\.\s*Разом", text)[0].strip().rstrip(".").strip()
    if not label:
        return None
    click = CLICK_ID.get(label.split("/")[0].strip().lower())
    return f"{label} ({click})" if click else label


def _has_site_marker(order: dict) -> bool:
    return SITE_MARKER in (order.get("managerComment") or "")


def _is_bot_order(order: dict) -> bool:
    return ((order.get("salesChannel") or {}).get("title") or "").strip() == BOT_SALES_CHANNEL


def is_site_order(order: dict) -> bool:
    """True якщо замовлення з сайту: маркер у коментарі або канал Telegram-бота сайту."""
    return _has_site_marker(order) or _is_bot_order(order)


def parse_site_order(order: dict) -> Optional[Dict]:
    """
    Повертає dict із розібраними полями сайт-замовлення, або None якщо не сайт
    або якщо статус не рахується («Новий», «Відмінено», «Не підтверджено»).
    """
    if not is_site_order(order):
        return None
    if not is_countable_order(order):
        return None
    if _has_site_marker(order):
        ad_label = _extract_ad_label(order.get("managerComment") or "") or "Без реклами (прямі)"
    else:
        ad_label = BOT_AD_LABEL
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
        orders = await sitniks.get_orders_exact(date_from, date_to)
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
