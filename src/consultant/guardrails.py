"""Запобіжники: коли передавати людині й коли зупиняти дожими. Чисті функції."""
from __future__ import annotations

# Якщо клієнт пише таке — одразу ескалюємо до людини, агент не імпровізує.
ESCALATE_TRIGGERS = [
    "юрист", "адвокат", "суд", "поліц", "скарг", "шахра", "поверніть гроші",
    "верну деньги", "возврат", "обман", "наклада", "директор", "керівник",
]

MAX_FOLLOWUPS = 4  # більше дожимів = спам


def should_escalate(text: str) -> bool:
    t = (text or "").lower()
    return any(trigger in t for trigger in ESCALATE_TRIGGERS)


def can_followup(followups_sent: int) -> bool:
    return followups_sent < MAX_FOLLOWUPS


# Каденція нагадувань: чим далі — тим рідше. None = більше не нагадувати.
_CADENCE_HOURS = [2, 24, 72, 168]  # +2 год, +1 день, +3 дні, +7 днів


def next_followup_hours(followups_sent: int) -> float | None:
    """Через скільки годин слати наступний дожим (з урахуванням уже відправлених)."""
    if followups_sent >= len(_CADENCE_HOURS):
        return None
    return float(_CADENCE_HOURS[followups_sent])
