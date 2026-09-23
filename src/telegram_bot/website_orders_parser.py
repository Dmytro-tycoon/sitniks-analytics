"""
Парсер повідомлень "SKIN-ONE Assistant" з групи "SKIN.ONE заявки з сайту".

Формат повідомлення:
    🛒 Нове замовлення з сайту 10b82459

    Брижак Світлана, +380990319017
    Зв'язок: Viber

    Доставка: Нова Пошта, поштомат: ...
    Оплата: накладений платіж, передоплата 200 грн, при отриманні 689 грн

    • Крем-пілінг гоммаж Renew, 30 мл × 1 = 499 грн
    • ...

    Разом: 889 грн

    Реклама: meta / skinone_catalog_2209 / 120260678712650059 / catalog (fbclid)
    Знижка 10% на перше замовлення: перевірити, чи це перше замовлення
"""
import re
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

RE_ORDER_ID = re.compile(r"Нове замовлення з сайту\s+(\S+)", re.I)
RE_TOTAL    = re.compile(r"Разом:\s*([\d\s]+(?:[.,]\d+)?)\s*грн", re.I)
RE_AD       = re.compile(r"Реклама:\s*(.+?)(?:\n|$)", re.I)
# Ім'я і телефон часто в одному рядку після заголовка. Приклад:
# "Брижак Світлана, +380990319017"
RE_CLIENT   = re.compile(r"^([^\n,]+?),\s*(\+?\d[\d\s\-]{7,})", re.M)


def parse_order_message(text: str) -> Optional[Dict]:
    """Розпарсити повідомлення. Повертає dict або None якщо це не замовлення."""
    if not text:
        return None
    m_oid = RE_ORDER_ID.search(text)
    if not m_oid:
        return None  # не замовлення

    order_id = m_oid.group(1).strip()

    total = None
    m_total = RE_TOTAL.search(text)
    if m_total:
        raw = m_total.group(1).replace(" ", "").replace(",", ".")
        try:
            total = float(raw)
        except ValueError:
            pass

    ad_label = None
    m_ad = RE_AD.search(text)
    if m_ad:
        ad_label = m_ad.group(1).strip()

    client_name = None
    client_phone = None
    m_c = RE_CLIENT.search(text)
    if m_c:
        client_name = m_c.group(1).strip()
        client_phone = re.sub(r"[\s\-]", "", m_c.group(2))

    return {
        "order_id": order_id,
        "total_uah": total,
        "ad_label": ad_label,
        "client_name": client_name,
        "client_phone": client_phone,
    }
