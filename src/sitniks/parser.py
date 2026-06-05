from datetime import datetime
from typing import List, Dict
import pytz

KIEV = pytz.timezone("Europe/Kiev")


def to_kiev_str(iso_ts: str) -> str:
    """ISO 8601 (UTC) → "2026-06-04 14:27" у Київському часі."""
    if not iso_ts:
        return ""
    try:
        # Sitniks віддає типу "2026-06-02T07:52:27.444Z"
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(KIEV).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_ts[:16].replace("T", " ")


def format_dialog_for_claude(messages: List[Dict], owner_id: str = None) -> str:
    """Перетворює список повідомлень у текст для аналізу Claude (час — Київ)."""
    lines = []
    for msg in messages:
        text = msg.get("text", "").strip()
        if not text:
            continue

        manager_name = msg.get("managerName", "")
        timestamp = to_kiev_str(msg.get("createdAt", ""))

        sender = f"МЕНЕДЖЕР ({manager_name})" if manager_name else "КЛІЄНТ"
        lines.append(f"[{timestamp}] {sender}: {text}")

    return "\n".join(lines)
