"""
Які замовлення рахуємо у звітах по рекламі (Google Sheet).

Не рахуємо замовлення зі статусами (title у Sitniks, GET /orders/statuses):
  - "Новий"            — заявка, менеджер ще не оформив / не оплачено
  - "Відмінено"        — скасоване
  - "Не підтверджено"  — клієнт не підтвердив
  - "Відмовилась"      — клієнт відмовився (тип canceled)
  - "Очікуємо оплату"  — ще не оплачено (тип new; у Sitniks title з пробілом у кінці)
Решта статусів ("В роботі", "ТТН сформовано", "Виконано" тощо) — рахуються.
"""

EXCLUDED_STATUS_TITLES = {"Новий", "Відмінено", "Не підтверджено", "Відмовилась", "Очікуємо оплату"}


def status_title(order: dict) -> str:
    return ((order.get("status") or {}).get("title") or "").strip()


def is_countable_order(order: dict) -> bool:
    """False для замовлень зі статусами з EXCLUDED_STATUS_TITLES."""
    return status_title(order) not in EXCLUDED_STATUS_TITLES
