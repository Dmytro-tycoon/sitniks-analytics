"""
Які замовлення рахуємо у звітах по рекламі (Google Sheet).

Не рахуємо замовлення зі статусами (title у Sitniks, GET /orders/statuses):
  - "Новий"            — заявка, менеджер ще не оформив / не оплачено
  - "Відмінено"        — скасоване
  - "Не підтверджено"  — клієнт не підтвердив
  - "Відмовилась"      — клієнт відмовився (тип canceled)
  - "Очікуємо оплату"  — ще не оплачено (тип new; у Sitniks title з пробілом у кінці)
  - "Не було в наявності" — товару не було, замовлення не відбулось (додано 28.10.2026)
Решта статусів ("В роботі", "ТТН сформовано", "Виконано" тощо) — рахуються.
"""

EXCLUDED_STATUS_TITLES = {"Новий", "Відмінено", "Не підтверджено", "Відмовилась", "Очікуємо оплату",
                          "Не було в наявності"}


def status_title(order: dict) -> str:
    return ((order.get("status") or {}).get("title") or "").strip()


_FORCE = None


def _force_count() -> set:
    """config/morning_overrides.json → count_orders: № замовлень, які рахуємо попри статус-відміну
    (рішення користувача, напр. №19327 — відміна була технічним збоєм, 28.11.2026)."""
    global _FORCE
    if _FORCE is None:
        import json, os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "config", "morning_overrides.json")
        try:
            _FORCE = {str(x) for x in json.load(open(path, encoding="utf-8")).get("count_orders", [])}
        except Exception:
            _FORCE = set()
    return _FORCE


def is_countable_order(order: dict) -> bool:
    """False для замовлень зі статусами з EXCLUDED_STATUS_TITLES (крім count_orders з overrides)."""
    if str(order.get("orderNumber")) in _force_count():
        return True
    return status_title(order) not in EXCLUDED_STATUS_TITLES
