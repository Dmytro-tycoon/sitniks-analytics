"""Фільтрація діалогів — не запускаємо дорогий аналіз на тих, де нема що аналізувати."""
from typing import List, Dict, Tuple


def should_analyze(messages: List[Dict]) -> Tuple[bool, str]:
    """
    Повертає (треба_аналізувати, причина_якщо_ні).
    Скіпаємо:
    - менше 2 повідомлень всього
    - менеджер не написав жодного повідомлення (показуємо окремо у звіті)
    - клієнт не написав жодного повідомлення (одностороннє привітання — не аналізуємо)
    """
    if len(messages) < 2:
        return False, "too_short"

    has_manager = any(m.get("managerName") for m in messages)
    has_client = any(not m.get("managerName") for m in messages)

    if not has_manager:
        return False, "no_manager_response"
    if not has_client:
        return False, "no_client_message"

    return True, ""
