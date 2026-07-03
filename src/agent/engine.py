"""Движок діалогу агента-продавця: формує відповідь і дожими через Claude.

Працює на спільному "мозку": business_context + плейбук кращих менеджерів.
"""
from __future__ import annotations

from src.agent.guardrails import next_followup_hours, should_escalate
from src.agent.memory import Conversation
from src.agent.prompts import (
    FOLLOWUP_PROMPT,
    SELLER_SYSTEM_PROMPT,
    SELLER_USER_PROMPT,
)
from src.claude.llm import complete_json
from src.config import settings


async def respond(conv: Conversation, playbook: str = "") -> dict:
    """Згенерувати наступну відповідь клієнту й оновити стан розмови."""
    last = conv.last_client_message()

    # Жорсткий запобіжник до виклику моделі
    if should_escalate(last):
        conv.status = "escalated"
        return {
            "reply": "Передаю ваш запит керівнику — він звʼяжеться з вами найближчим часом 🙏",
            "stage": conv.stage,
            "escalate": True,
            "escalate_reason": "тригер ескалації у повідомленні клієнта",
            "wants_order": False,
            "order": None,
            "followup_hours": 0,
        }

    system = SELLER_SYSTEM_PROMPT.format(
        niche=settings.niche or "продажів",
        business_context=settings.business_context or "—",
        playbook=playbook or "—",
    )
    user = SELLER_USER_PROMPT.format(history=conv.history_text(), last_message=last)

    result = await complete_json(user, system=system, model=settings.models.get("reply"), max_tokens=1200)

    # Оновлюємо стан
    conv.stage = result.get("stage", conv.stage)
    if result.get("escalate"):
        conv.status = "escalated"
    elif result.get("wants_order"):
        conv.status = "won"
    conv.next_followup_hours = float(result.get("followup_hours") or 0)
    return result


async def followup_message(conv: Conversation) -> dict:
    """Згенерувати чергове нагадування клієнту, що замовк."""
    result = await complete_json(
        FOLLOWUP_PROMPT.format(
            attempt=conv.followups_sent + 1,
            business_context=settings.business_context or "—",
            history=conv.history_text(),
        ),
        max_tokens=600,
    )
    if result.get("give_up"):
        conv.status = "lost"
    else:
        conv.followups_sent += 1
        nxt = next_followup_hours(conv.followups_sent)
        conv.next_followup_hours = nxt or 0.0
        if nxt is None:
            conv.status = "lost"
    return result
