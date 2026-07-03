"""Памʼять діалогів агента-продавця.

За замовчуванням — у памʼяті процесу (працює одразу, без БД, годиться для пісочниці).
Для продакшну зберігай у Supabase (таблиця conversations) — функції-серіалізатори нижче.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Turn:
    role: str   # "client" | "agent"
    text: str


@dataclass
class Conversation:
    lead_id: str                       # id ліда (telegram user id або sitniks chatId)
    channel: str                       # "telegram" | "instagram" | "sitniks"
    turns: list[Turn] = field(default_factory=list)
    stage: str = "contact"
    status: str = "active"             # active | won | lost | escalated
    followups_sent: int = 0
    next_followup_hours: float = 0.0   # коли наступне нагадування (0 = не заплановано)

    def add(self, role: str, text: str) -> None:
        self.turns.append(Turn(role, text))

    def history_text(self) -> str:
        who = {"client": "КЛІЄНТ", "agent": "МЕНЕДЖЕР"}
        return "\n".join(f"{who.get(t.role, t.role)}: {t.text}" for t in self.turns)

    def last_client_message(self) -> str:
        for t in reversed(self.turns):
            if t.role == "client":
                return t.text
        return ""

    def to_row(self) -> dict:
        d = asdict(self)
        return d


class ConversationStore:
    """Простий in-memory стор. Ключ — (channel, lead_id)."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], Conversation] = {}

    def get_or_create(self, lead_id: str, channel: str) -> Conversation:
        key = (channel, str(lead_id))
        if key not in self._store:
            self._store[key] = Conversation(lead_id=str(lead_id), channel=channel)
        return self._store[key]

    def all_active(self) -> list[Conversation]:
        return [c for c in self._store.values() if c.status == "active"]


# Єдиний інстанс на процес (для пісочниці/одного воркера)
store = ConversationStore()
