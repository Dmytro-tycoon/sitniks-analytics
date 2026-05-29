import json
import asyncio
from anthropic import AsyncAnthropic, RateLimitError
from src.config import settings
from src.claude.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT

WEIGHTS = {
    "response_speed": 0.10,
    "tone": 0.15,
    "needs_discovery": 0.20,
    "expertise": 0.20,
    "objection_handling": 0.10,
    "closing": 0.15,
    "upsell": 0.10,
}


def normalize_result(raw: dict) -> dict:
    """Нормалізуємо стислий формат до повного: scores з comments, overall_score."""
    scores_raw = raw.get("scores", {})
    reasons = raw.get("low_score_reasons", {})

    scores = {}
    overall = 0.0
    for crit, weight in WEIGHTS.items():
        s = scores_raw.get(crit, 0)
        if isinstance(s, dict):
            s = s.get("score", 0)
        scores[crit] = {
            "score": s,
            "weight": weight,
            "comment": reasons.get(crit, ""),
        }
        overall += s * weight

    return {
        "scores": scores,
        "overall_score": round(overall, 2),
        "alerts": [
            {
                "type": "critical" if a.get("code", "").startswith("CR") else "warning",
                "code": a.get("code"),
                "description": a.get("desc", ""),
                "quote": a.get("quote", ""),
            }
            for a in (raw.get("alerts") or [])
        ],
        "strengths": [],  # тримаємо ключ для сумісності з reports.py
        "improvements": [],
        "summary": raw.get("summary", ""),
        "is_template_dialog": raw.get("is_template_dialog", False),
    }


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def build_messages(manager_name: str, chat_status: str, started_at: str, dialog_text: str):
    prompt = ANALYSIS_PROMPT.format(
        manager_name=manager_name,
        chat_status=chat_status,
        started_at=started_at,
        dialog_text=dialog_text,
    )
    return [{"role": "user", "content": prompt}]


def build_system():
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


class ClaudeAnalyzer:
    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-6"

    async def analyze_dialog(self, dialog_text, manager_name, chat_status, started_at) -> dict:
        backoff = 15
        for attempt in range(6):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=1500,
                    system=build_system(),
                    messages=build_messages(manager_name, chat_status, started_at, dialog_text),
                )
                break
            except RateLimitError:
                if attempt == 5:
                    raise
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)

        raw = _parse_json(response.content[0].text)
        return normalize_result(raw)
