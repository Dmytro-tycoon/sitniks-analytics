"""Універсальний інтерфейс до будь-якої CRM.

Аналізатор працює ТІЛЬКИ з нормалізованими Dialog/Message,
тому додати нову CRM = написати один клас-конектор, не чіпаючи решту коду.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class Message:
    sender: str          # "client" | "manager"
    text: str
    timestamp: datetime
    author_name: str = ""


@dataclass
class Dialog:
    id: str
    date: datetime
    manager_name: str
    messages: list[Message] = field(default_factory=list)
    status: str = ""           # напр. "ordered" | "open" | "lost"
    raw: dict | None = None     # сирий обʼєкт з CRM для дебагу


@runtime_checkable
class CRMConnector(Protocol):
    """Контракт, який має реалізувати конектор кожної CRM."""

    async def get_dialogs(self, date_from: datetime, date_to: datetime) -> list[Dialog]:
        """Повернути нормалізовані діалоги за період (з повідомленнями)."""
        ...

    async def close(self) -> None:
        ...


def get_connector(provider: str) -> CRMConnector:
    """Фабрика конекторів за назвою провайдера з конфігу клієнта."""
    if provider == "sitniks":
        from src.crm.sitniks import SitniksConnector

        return SitniksConnector()
    raise ValueError(f"Невідомий CRM-провайдер: {provider}. Доступні: sitniks.")
