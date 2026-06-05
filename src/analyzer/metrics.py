from datetime import datetime
from typing import List, Dict
import pytz

KIEV = pytz.timezone("Europe/Kiev")
WORK_START_HOUR = 8
WORK_END_HOUR = 23  # включно по 22:59


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def count_client_msgs_in_work_hours(messages: List[Dict]) -> int:
    """Скільки клієнтських повідомлень припало на робочий час 09:00-22:00 Київ."""
    cnt = 0
    for m in messages:
        if m.get("managerName"):
            continue
        try:
            kt = _parse(m["createdAt"]).astimezone(KIEV)
            if WORK_START_HOUR <= kt.hour < WORK_END_HOUR:
                cnt += 1
        except Exception:
            continue
    return cnt


def calculate_response_times(messages: List[Dict]) -> Dict:
    """Час відповіді менеджера на повідомлення клієнта (хв)"""
    response_times = []
    first_response = None

    # Сортуємо за часом
    messages = sorted(messages, key=lambda m: m.get("createdAt", ""))

    for i, msg in enumerate(messages):
        is_client = not msg.get("managerName")
        if not is_client or i + 1 >= len(messages):
            continue

        next_msg = messages[i + 1]
        next_is_manager = bool(next_msg.get("managerName"))
        if not next_is_manager:
            continue

        try:
            delta = (_parse(next_msg["createdAt"]) - _parse(msg["createdAt"])).total_seconds() / 60
            response_times.append(delta)
            if first_response is None:
                first_response = delta
        except Exception:
            continue

    if not response_times:
        return {"avg": 0.0, "max": 0.0, "first": 0.0}

    return {
        "avg": round(sum(response_times) / len(response_times), 2),
        "max": round(max(response_times), 2),
        "first": round(first_response or 0, 2),
    }


def calculate_duration(messages: List[Dict]) -> float:
    if not messages:
        return 0.0
    times = [_parse(m["createdAt"]) for m in messages if m.get("createdAt")]
    if not times:
        return 0.0
    return round((max(times) - min(times)).total_seconds() / 60, 2)


def calculate_metrics(chat: Dict, messages: List[Dict]) -> Dict:
    return {
        "messages_count": len(messages),
        "messages_from_manager": sum(1 for m in messages if m.get("managerName")),
        "client_msgs_in_work_hours": count_client_msgs_in_work_hours(messages),
        "response_times": calculate_response_times(messages),
        "duration_minutes": calculate_duration(messages),
        "has_order": chat.get("status", "").lower() in ("ordered", "замовлення", "оплачено"),
    }
