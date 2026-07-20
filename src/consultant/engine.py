"""Движок агента-консультанта: веде кваліфікацію і передає діалог живому консультанту.

Агент НЕ підбирає засоби й не називає ціни — він доводить клієнтку до моменту підбору
і передає (handoff) дівчатам-консультантам. Працює на sales_context + плейбуку кваліфікації.
"""
from __future__ import annotations

from src.consultant.guardrails import next_followup_hours, should_escalate
from src.consultant.memory import Conversation
from src.consultant.pricecards import find_card, is_price_question
from src.consultant.prompts import (
    FOLLOWUP_PROMPT,
    QUALIFIER_SYSTEM_PROMPT,
    QUALIFIER_USER_PROMPT,
)
from src.claude.llm import complete_json
from src.config import settings


async def respond(conv: Conversation, playbook: str = "", ad_title: str | None = None) -> dict:
    """Згенерувати наступну відповідь клієнтці й оновити стан розмови.

    ad_title — заголовок реклами, з якої прийшла клієнтка (якщо відомо): допомагає
    знайти правильну картку товару на запит ціни.
    """
    last = conv.last_client_message()

    # Жорсткий запобіжник до виклику моделі
    if should_escalate(last):
        conv.status = "escalated"
        return {
            "reply": "Передаю ваш запит керівнику — він звʼяжеться з вами найближчим часом 🙏",
            "stage": conv.stage,
            "escalate": True,
            "escalate_reason": "тригер ескалації у повідомленні клієнта",
            "handoff": False,
            "handoff_summary": None,
            "followup_hours": 0,
        }

    # На запит ціни підтягуємо картку потрібного товару (як відповідають дівчата)
    price_card = ""
    if is_price_question(last) or ad_title:
        price_card = find_card(ad_title, last)

    system = QUALIFIER_SYSTEM_PROMPT.format(
        niche=settings.niche or "професійної косметики",
        business_context=settings.sales_context or "—",
        playbook=playbook or "—",
        price_card=price_card or "— (картки немає — ціну не називай, уточни який засіб цікавить)",
    )
    user = QUALIFIER_USER_PROMPT.format(history=conv.history_text(), last_message=last)

    # system стабільний (персона+плейбук) → кешуємо
    result = await complete_json(
        user, system=system, model=settings.models.get("reply"), max_tokens=1000, cache_system=True
    )

    # Оновлюємо стан
    conv.stage = result.get("stage", conv.stage)
    if result.get("escalate"):
        conv.status = "escalated"
    elif result.get("handoff"):
        conv.status = "handoff"  # передано живому консультанту — агент більше не веде діалог
    conv.next_followup_hours = float(result.get("followup_hours") or 0)
    return result


async def followup_message(conv: Conversation) -> dict:
    """Згенерувати нагадування клієнтці, що замовкла, не завершивши кваліфікацію."""
    result = await complete_json(
        FOLLOWUP_PROMPT.format(
            attempt=conv.followups_sent + 1,
            business_context=settings.sales_context or "—",
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
