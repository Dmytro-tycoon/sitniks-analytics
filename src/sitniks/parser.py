from typing import List, Dict


def format_dialog_for_claude(messages: List[Dict], owner_id: str = None) -> str:
    """Перетворює список повідомлень у текст для аналізу Claude"""
    lines = []
    for msg in messages:
        text = msg.get("text", "").strip()
        if not text:
            continue

        sent_by = msg.get("sentBy", "")
        manager_name = msg.get("managerName", "")
        timestamp = msg.get("createdAt", "")[:16].replace("T", " ")

        # Якщо є ім'я менеджера — це повідомлення менеджера
        if manager_name:
            sender = f"МЕНЕДЖЕР ({manager_name})"
        else:
            sender = "КЛІЄНТ"

        lines.append(f"[{timestamp}] {sender}: {text}")

    return "\n".join(lines)
