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

import asyncio
from datetime import datetime

import httpx

from src.config import settings
from src.crm.base import Dialog, Message

PAGE = 50  # розмір сторінки пагінації (limit/skip). Sitniks: max limit для /messages = 50

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

    async def _get(self, url: str, params: dict | None = None) -> dict:
        """GET з retry на 429 (експоненційний backoff) — щоб поллер не падав на rate-limit."""
        backoff = 2
        for attempt in range(6):
            resp = await self.client.get(url, params=params)
            if resp.status_code == 429:
                if attempt == 5:
                    resp.raise_for_status()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            resp.raise_for_status()
            return resp.json()
        return {}

    async def get_dialogs(self, date_from: datetime, date_to: datetime, chat_filter=None) -> list[Dialog]:
        """Чати за період + їхні повідомлення, у нормалізованому вигляді.

        chat_filter(chat_dict) -> bool: якщо задано, повідомлення тягнемо ТІЛЬКИ для чатів,
        що проходять фільтр (напр. tiktok+новий). Це різко зменшує кількість запитів і 429."""
        chats = await self._get_all_chats(date_from, date_to)
        dialogs: list[Dialog] = []
        for c in chats:
            if chat_filter is not None and not chat_filter(c):
                continue
            messages = await self._get_chat_messages(c["id"], client_id=c.get("userId"))
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
            data = await self._get(
                f"{self.base_url}/chats",
                params={
                    "startDate": date_from.isoformat(),
                    "endDate": date_to.isoformat(),
                    "limit": PAGE,
                    "skip": skip,
                },
            )
            batch = data.get("data", [])
            out.extend(batch)
            if len(batch) < PAGE:
                break
            skip += PAGE
        return out

    async def _get_chat_messages(self, chat_id: str, client_id: str | None = None) -> list[Message]:
        out: list[Message] = []
        skip = 0
        while True:
            data = await self._get(
                f"{self.base_url}/chats/{chat_id}/messages",
                params={"limit": PAGE, "skip": skip},
            )
            batch = data.get("data", [])
            for m in batch:
                out.append(
                    Message(
                        sender=self._sender_of(m, client_id),
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
    def _sender_of(m: dict, client_id: str | None = None) -> str:
        """Клієнт чи менеджер.

        Найнадійніший сигнал — `sentBy == chat.userId` (акаунт клієнта): усе інше (owner
        компанії, менеджер, бот) → manager. Це коректно й тоді, коли managerName порожній
        (напр. картки/автовідповіді в TikTok/Instagram). Запасні сигнали — managerName і sentBy.
        """
        sent_by = (m.get("sentBy") or "").strip()
        if client_id and sent_by:
            return "client" if sent_by == client_id else "manager"
        if (m.get("managerName") or "").strip():
            return "manager"
        if sent_by.lower() in _MANAGER_SENDERS:
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
