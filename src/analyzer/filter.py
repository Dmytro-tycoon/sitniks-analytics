"""Фільтрація діалогів — не запускаємо дорогий аналіз на тих, де нема що аналізувати."""
from typing import List, Dict, Tuple


def should_analyze(messages: List[Dict]) -> Tuple[bool, str]:
    """
    Повертає (треба_аналізувати, причина_якщо_ні).
    Скіпаємо:
    - менше 4 повідомлень всього
    - менеджер не написав жодного повідомлення
    - клієнт не написав жодного повідомлення (тільки розсилка від менеджера)
    - сумарний текст менеджера < 50 символів (привітання, не діалог)
    """
    if len(messages) < 4:
        return False, "too_short"

    manager_msgs = [m for m in messages if m.get("managerName")]
    client_msgs = [m for m in messages if not m.get("managerName")]

    if not manager_msgs:
        return False, "no_manager_response"
    if not client_msgs:
        return False, "no_client_message"

    manager_text_len = sum(len((m.get("text") or "").strip()) for m in manager_msgs)
    if manager_text_len < 50:
        return False, "manager_text_minimal"

    return True, ""
