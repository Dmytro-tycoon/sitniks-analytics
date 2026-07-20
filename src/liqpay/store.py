"""
Зберігання замовлень LiqPay у Supabase (з ідемпотентністю callback-ів).

Таблиці (див. міграцію):
  liqpay_orders          — одне замовлення (order_id PK)
  liqpay_payment_events  — журнал callback-ів; UNIQUE(order_id, payment_id, status)

Функції синхронні (supabase-py sync). У async-хендлерах викликати через
`asyncio.to_thread(...)`, щоб не блокувати спільний event-loop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Переюзаємо вже налаштоване зʼєднання системи (єдина точка звʼязку зі спільним кодом)
from src.database.supabase_client import get_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_order(
    order_id: str,
    chat_id: int,
    amount: float,
    currency: str,
    description: str,
    paytype: str,
    payment_url: str,
) -> None:
    get_client().table("liqpay_orders").upsert({
        "order_id": order_id,
        "chat_id": chat_id,
        "amount": amount,
        "currency": currency,
        "description": description,
        "paytype": paytype,
        "status": "created",
        "payment_url": payment_url,
        "updated_at": _now_iso(),
    }, on_conflict="order_id").execute()


def record_payment_event(
    order_id: str,
    payment_id: Any,
    status: str,
    amount: Optional[float],
    currency: Optional[str],
    raw: dict[str, Any],
) -> bool:
    """
    Ідемпотентний запис події оплати.
    True  — подія НОВА (треба обробити),
    False — дублікат (order_id+payment_id+status уже бачили).
    """
    pid = "" if payment_id is None else str(payment_id)
    res = get_client().table("liqpay_payment_events").upsert(
        {
            "order_id": order_id,
            "payment_id": pid,
            "status": status,
            "amount": amount,
            "currency": currency,
            "raw_json": raw,
        },
        on_conflict="order_id,payment_id,status",
        ignore_duplicates=True,   # дублікат тихо ігнорується → data порожня
    ).execute()
    return bool(res.data)


def update_order_status(order_id: str, status: str) -> None:
    get_client().table("liqpay_orders").update({
        "status": status,
        "updated_at": _now_iso(),
    }).eq("order_id", order_id).execute()


def get_order(order_id: str) -> Optional[dict[str, Any]]:
    res = get_client().table("liqpay_orders").select("*").eq("order_id", order_id).execute()
    return res.data[0] if res.data else None


def list_orders_by_chat(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    res = (
        get_client().table("liqpay_orders")
        .select("*")
        .eq("chat_id", chat_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []
