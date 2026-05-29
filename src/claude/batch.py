"""
Анализ через Anthropic Message Batches API — 50% знижка vs синхронні виклики.
Підходить для нічного daily-job. Очікувана затримка: 5-30 хвилин.
"""
import asyncio
from typing import List, Dict
from anthropic import AsyncAnthropic
from anthropic.types.messages.batch_create_params import Request
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming

from src.config import settings
from src.claude.client import build_messages, build_system, normalize_result, _parse_json


class ClaudeBatchAnalyzer:
    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-6"

    async def submit_batch(self, items: List[Dict]) -> str:
        """
        items: список {custom_id, manager_name, chat_status, started_at, dialog_text}
        Повертає batch_id.
        """
        requests = []
        for it in items:
            requests.append(
                Request(
                    custom_id=it["custom_id"],
                    params=MessageCreateParamsNonStreaming(
                        model=self.model,
                        max_tokens=1500,
                        system=build_system(),
                        messages=build_messages(
                            manager_name=it["manager_name"],
                            chat_status=it["chat_status"],
                            started_at=it["started_at"],
                            dialog_text=it["dialog_text"],
                        ),
                    ),
                )
            )

        batch = await self.client.messages.batches.create(requests=requests)
        return batch.id

    async def wait_for_batch(self, batch_id: str, poll_interval: int = 30, max_wait: int = 3600) -> Dict:
        """Чекаємо завершення. Повертаємо {custom_id: normalized_result}."""
        elapsed = 0
        while elapsed < max_wait:
            batch = await self.client.messages.batches.retrieve(batch_id)
            print(f"[batch {batch_id[:10]}] status={batch.processing_status} "
                  f"processed={batch.request_counts.processing}/{batch.request_counts.processing + batch.request_counts.succeeded + batch.request_counts.errored}")
            if batch.processing_status == "ended":
                break
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        else:
            raise TimeoutError(f"Batch {batch_id} не завершився за {max_wait}s")

        # Завантажуємо результати
        results = {}
        async for entry in await self.client.messages.batches.results(batch_id):
            cid = entry.custom_id
            if entry.result.type == "succeeded":
                try:
                    text = entry.result.message.content[0].text
                    raw = _parse_json(text)
                    results[cid] = normalize_result(raw)
                except Exception as e:
                    print(f"❌ {cid}: parse error: {e}")
                    results[cid] = None
            else:
                print(f"❌ {cid}: {entry.result.type}")
                results[cid] = None

        return results

    async def analyze_batch(self, items: List[Dict]) -> Dict:
        """Зручний обгортач: submit + wait + повернути результати."""
        if not items:
            return {}
        batch_id = await self.submit_batch(items)
        print(f"✅ Batch створено: {batch_id} ({len(items)} запитів)")
        return await self.wait_for_batch(batch_id)
