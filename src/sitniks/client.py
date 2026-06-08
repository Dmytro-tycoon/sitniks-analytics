import asyncio
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

    async def _get_with_retry(self, url: str, params: dict = None) -> dict:
        """GET з retry на 429 (експоненційний backoff)."""
        backoff = 2
        for attempt in range(6):
            response = await self.client.get(url, headers=self.headers, params=params)
            if response.status_code == 429:
                if attempt == 5:
                    response.raise_for_status()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            response.raise_for_status()
            return response.json()
        return {}

    async def get_chats(
        self,
        date_from: datetime,
        date_to: datetime,
        limit: int = 50,
        skip: int = 0,
        by_first_message: bool = False,
    ) -> Dict:
        """by_first_message=True → фільтр за датою першого повідомлення клієнта
        (це Sitniks-логіка "Нові чати"). False → фільтр за createdAt чату."""
        if by_first_message:
            params = {
                "firstMessageStartDate": date_from.isoformat(),
                "firstMessageEndDate": date_to.isoformat(),
            }
        else:
            params = {
                "startDate": date_from.isoformat(),
                "endDate": date_to.isoformat(),
            }
        params["limit"] = limit
        params["skip"] = skip
        return await self._get_with_retry(f"{self.base_url}/chats", params=params)

    async def get_all_chats(self, date_from: datetime, date_to: datetime, by_first_message: bool = False) -> List[Dict]:
        """Отримати всі чати за період з пагінацією."""
        all_chats = []
        skip = 0
        limit = 50
        while True:
            result = await self.get_chats(date_from, date_to, limit=limit, skip=skip, by_first_message=by_first_message)
            chats = result.get("data", [])
            all_chats.extend(chats)
            if len(all_chats) >= result.get("count", 0) or not chats:
                break
            skip += limit
        return all_chats

    async def get_chat_messages(self, chat_id: str) -> List[Dict]:
        """Усі повідомлення чату через пагінацію (API віддає 10 за замовченням,
        50 максимум, без поля count — циклимо доки порожньо). Сортуємо за часом."""
        all_msgs = []
        skip = 0
        limit = 50
        while True:
            data = await self._get_with_retry(
                f"{self.base_url}/chats/{chat_id}/messages",
                params={"limit": limit, "skip": skip},
            )
            page = data.get("data", [])
            if not page:
                break
            all_msgs.extend(page)
            if len(page) < limit:
                break
            skip += limit
            if skip >= 1000:  # safety, на випадок «нескінченних» чатів
                break
        # Сортуємо за часом (від раннього до пізнього)
        all_msgs.sort(key=lambda m: m.get("createdAt", ""))
        return all_msgs

    async def get_chat(self, chat_id: str) -> Dict:
        return await self._get_with_retry(f"{self.base_url}/chats/{chat_id}")

    async def get_orders(self, date_from: datetime, date_to: datetime) -> List[Dict]:
        """Тягнемо всі замовлення за період (через пагінацію)."""
        all_orders = []
        skip = 0
        limit = 50
        while True:
            params = {
                "createdAtFrom": date_from.isoformat(),
                "createdAtTo": date_to.isoformat(),
                "limit": limit,
                "skip": skip,
            }
            data = await self._get_with_retry(f"{self.base_url}/orders", params=params)
            orders = data.get("data", [])
            all_orders.extend(orders)
            if len(all_orders) >= data.get("count", 0) or not orders:
                break
            skip += limit
        return all_orders

    async def get_ad_info_for_chat(self, chat_id: str) -> Optional[dict]:
        """Повертає adInfo з першого повідомлення чату (або None якщо нема).
        API повертає повідомлення від найновіших до найстаріших — щоб знайти
        перше (рекламне) повідомлення, перебираємо сторінки доки не дійдемо
        до самого раннього, або зупиняємось якщо adInfo знайдено раніше."""
        try:
            skip = 0
            limit = 50
            last_ad = None
            while True:
                data = await self._get_with_retry(
                    f"{self.base_url}/chats/{chat_id}/messages",
                    params={"limit": limit, "skip": skip},
                )
                msgs = data.get("data", [])
                if not msgs:
                    break
                # Перевіряємо кожне повідомлення на adInfo
                for msg in msgs:
                    ad = msg.get("adInfo")
                    if ad and ad.get("adTitle"):
                        last_ad = ad  # зберігаємо — найстаріший adInfo буде останнім знайденим
                if len(msgs) < limit:
                    break  # остання сторінка
                skip += limit
                if skip >= 1000:
                    break
            return last_ad
        except Exception:
            pass
        return None

    async def update_chat_tags(self, chat_id: str, tags: List[str]) -> Dict:
        """PUT /chats/{id} — оновити теги чату (єдине доступне через Open API поле)."""
        response = await self.client.put(
            f"{self.base_url}/chats/{chat_id}",
            headers=self.headers,
            json={"tags": tags},
        )
        response.raise_for_status()
        return response.json()

    async def close(self):
        await self.client.aclose()
