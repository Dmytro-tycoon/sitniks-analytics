"""Тонкий помічник для виклику Claude з гарантованим JSON на виході."""
from __future__ import annotations

import json

from anthropic import AsyncAnthropic

from src.config import settings


def parse_json(text: str) -> dict:
    """Claude інколи обгортає у ```json ... ``` — акуратно розбираємо."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
    return json.loads(t.strip())


async def complete_json(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 1500,
) -> dict:
    model = model or settings.models.get("rag") or settings.models["analysis"]
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    resp = await AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY).messages.create(**kwargs)
    return parse_json(resp.content[0].text)
