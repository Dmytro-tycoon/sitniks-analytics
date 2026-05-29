import httpx
from typing import List, Dict, Optional
from datetime import datetime
from src.config import settings


class SitniksClient:
    def __init__(self):
        self.base_url = settings.SITNIKS_API_URL
        self.headers = {
            "Authorization": f"Bearer {settings.SITNIKS_API_KEY}",
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient(timeout=30.0)

    async def get_chats(
        self,
        date_from: datetime,
        date_to: datetime,
        limit: int = 50,
        skip: int = 0
    ) -> Dict:
        params = {
            "startDate": date_from.isoformat(),
            "endDate": date_to.isoformat(),
            "limit": limit,
            "skip": skip
        }
        response = await self.client.get(
            f"{self.base_url}/chats",
            headers=self.headers,
            params=params
        )
        response.raise_for_status()
        return response.json()

    async def get_all_chats(self, date_from: datetime, date_to: datetime) -> List[Dict]:
        """Отримати всі чати за період з пагінацією"""
        all_chats = []
        skip = 0
        limit = 50

        while True:
            result = await self.get_chats(date_from, date_to, limit=limit, skip=skip)
            chats = result.get("data", [])
            all_chats.extend(chats)

            if len(all_chats) >= result.get("count", 0) or not chats:
                break
            skip += limit

        return all_chats

    async def get_chat_messages(self, chat_id: str) -> List[Dict]:
        response = await self.client.get(
            f"{self.base_url}/chats/{chat_id}/messages",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json().get("data", [])

    async def get_chat(self, chat_id: str) -> Dict:
        response = await self.client.get(
            f"{self.base_url}/chats/{chat_id}",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()
