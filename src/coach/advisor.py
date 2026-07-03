"""Блок 3: помічник менеджера/РОПа — підказки, відпрацювання заперечень,
рекомендації та персональний план зростання. Працює через Claude."""
from __future__ import annotations

import json

from src.claude.llm import complete_json
from src.claude.sales_prompts import (
    GROWTH_PLAN_PROMPT,
    MANAGER_RECO_PROMPT,
    OBJECTION_PROMPT,
    SUGGEST_REPLY_PROMPT,
)
from src.config import settings


async def suggest_reply(dialog_text: str, playbook: str = "") -> dict:
    """Підказати менеджеру найкращу наступну відповідь клієнту."""
    return await complete_json(
        SUGGEST_REPLY_PROMPT.format(
            niche=settings.niche or "продажів",
            business_context=settings.business_context or "—",
            playbook=playbook or "—",
            dialog_text=dialog_text,
        ),
        model=settings.models.get("reply"),
    )


async def handle_objection(objection: str, playbook: str = "") -> dict:
    return await complete_json(
        OBJECTION_PROMPT.format(
            objection=objection,
            niche=settings.niche or "продажів",
            business_context=settings.business_context or "—",
            playbook=playbook or "—",
        ),
        model=settings.models.get("reply"),
    )


async def growth_plan(manager_name: str, effectiveness: dict) -> dict:
    return await complete_json(
        GROWTH_PLAN_PROMPT.format(
            manager_name=manager_name,
            summary_json=json.dumps(effectiveness, ensure_ascii=False),
        )
    )


async def manager_recommendations(manager_name: str, effectiveness: dict) -> dict:
    """Рекомендації керівнику по конкретному менеджеру."""
    return await complete_json(
        MANAGER_RECO_PROMPT.format(
            manager_name=manager_name,
            summary_json=json.dumps(effectiveness, ensure_ascii=False),
        )
    )
