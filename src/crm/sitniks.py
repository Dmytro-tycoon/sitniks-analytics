"""Конектор до Sitniks CRM — пряма інтеграція через офіційний Open API.

Базовано на реальній специфікації: https://crm.sitniks.com/open-api
  Base URL:  https://crm.sitniks.com/open-api
  Auth:      Authorization: Bearer <token>
  Діалоги:   GET  /chats                      (список чатів за період)
             GET  /chats/{chatId}/messages     (повідомлення в чаті)
             POST /chats/{chatId}/messages     (надіслати повідомлення — для автопілота)
             GET  /managers                    (менеджери компанії)
"""
from __future__ import annotations

from datetime import datetime

import httpx

from src.config import settings
from src.crm.base import Dialog, Message

PAGE = 100  # розмір сторінки пагінації (limit/skip)

# Значення sentBy, що означають "це писав менеджер/компанія, а не клієнт".
_MANAGER_SENDERS = {"manager", "operator", "company", "bot", "out", "outgoing"}


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.min
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class SitniksConnector:
    def __init__(self) -> None:
        self.base_url = settings.SITNIKS_API_URL.rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {settings.SITNIKS_API_KEY}",
                "Content-Type": "application/json",
            },
        )

    async def get_dialogs(self, date_from: datetime, date_to: datetime) -> list[Dialog]:
        """Усі чати за період + їхні повідомлення, у нормалізованому вигляді."""
        chats = await self._get_all_chats(date_from, date_to)
        dialogs: list[Dialog] = []
        for c in chats:
            messages = await self._get_chat_messages(c["id"])
            dialogs.append(
                Dialog(
                    id=str(c["id"]),
                    date=_parse_dt(c.get("createdAt") or c.get("lastMessageCreatedAt")),
                    manager_name=c.get("assignedManagerName") or "",
                    status=c.get("status", "") or "",
                    messages=messages,
                    raw=c,
                )
            )
        return dialogs

    async def _get_all_chats(self, date_from: datetime, date_to: datetime) -> list[dict]:
        out: list[dict] = []
        skip = 0
        while True:
            resp = await self.client.get(
                f"{self.base_url}/chats",
                params={
                    "startDate": date_from.isoformat(),
                    "endDate": date_to.isoformat(),
                    "limit": PAGE,
                    "skip": skip,
                },
            )
            resp.raise_for_status()
            batch = resp.json().get("data", [])
            out.extend(batch)
            if len(batch) < PAGE:
                break
            skip += PAGE
        return out

    async def _get_chat_messages(self, chat_id: str) -> list[Message]:
        out: list[Message] = []
        skip = 0
        while True:
            resp = await self.client.get(
                f"{self.base_url}/chats/{chat_id}/messages",
                params={"limit": PAGE, "skip": skip},
            )
            resp.raise_for_status()
            batch = resp.json().get("data", [])
            for m in batch:
                out.append(
                    Message(
                        sender=self._sender_of(m),
                        text=m.get("text", "") or "",
                        timestamp=_parse_dt(m.get("createdAt")),
                        author_name=m.get("managerName", "") or "",
                    )
                )
            if len(batch) < PAGE:
                break
            skip += PAGE
        # Sitniks може віддавати від нових до старих — впорядковуємо за часом
        out.sort(key=lambda x: x.timestamp)
        return out

    @staticmethod
    def _sender_of(m: dict) -> str:
        """Менеджер чи клієнт. Надійний сигнал — заповнений managerName."""
        if (m.get("managerName") or "").strip():
            return "manager"
        if (m.get("sentBy") or "").lower() in _MANAGER_SENDERS:
            return "manager"
        return "client"

    async def send_message(self, chat_id: str, text: str) -> dict:
        """Надіслати повідомлення в чат (Фаза 4: копайлот/автопілот)."""
        resp = await self.client.post(
            f"{self.base_url}/chats/{chat_id}/messages",
            json={"text": text, "attachments": []},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_managers(self) -> list[dict]:
        resp = await self.client.get(f"{self.base_url}/managers", params={"limit": PAGE, "skip": 0})
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def close(self) -> None:
        await self.client.aclose()
