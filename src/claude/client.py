import json
import asyncio
from anthropic import AsyncAnthropic, RateLimitError
from src.config import settings
from src.claude.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT


class ClaudeAnalyzer:
    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-6"

    async def analyze_dialog(
        self,
        dialog_text: str,
        manager_name: str,
        chat_status: str,
        started_at: str,
    ) -> dict:
        prompt = ANALYSIS_PROMPT.format(
            manager_name=manager_name,
            chat_status=chat_status,
            started_at=started_at,
            dialog_text=dialog_text,
        )

        # Retry з експоненційним backoff при rate-limit
        backoff = 15
        for attempt in range(6):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=3000,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": prompt}],
                )
                break
            except RateLimitError:
                if attempt == 5:
                    raise
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)

        text = response.content[0].text.strip()
        # Прибираємо markdown-обгортку ```json ... ``` якщо є
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        result = json.loads(text)

        # Перерахуємо overall_score на основі ваг
        scores = result.get("scores", {})
        weights = {
            "response_speed": 0.10,
            "tone": 0.15,
            "needs_discovery": 0.20,
            "expertise": 0.20,
            "objection_handling": 0.10,
            "closing": 0.15,
            "upsell": 0.10,
        }
        overall = sum(
            scores[k]["score"] * w
            for k, w in weights.items()
            if k in scores
        )
        result["overall_score"] = round(overall, 2)

        return result
