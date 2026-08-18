"""Передача діалогу від агента-консультанта живій дівчині-консультанту.

Коли агент завершив кваліфікацію (handoff=true), він:
  1) ставить чату СТАТУС «🔥 Гарячий лід від Агента» у Sitniks — дівчата бачать його
     в мобільному додатку (де теги не видно) і розбирають по статусу;
  2) додатково шле анкету (резюме + лінк) у Telegram (як дубль-канал з контекстом).
Далі підбір засобів, ціни й оформлення робить людина.
"""
from __future__ import annotations

from src.config import settings

# Дедуплікація: не сповіщати двічі про той самий чат
_NOTIFIED: set[str] = set()


def _sitniks_link(chat_id: str) -> str:
    return f"https://web.sitniks.com/2341/chats/dialog/{chat_id}"


async def deliver_handoff(
    lead_id: str, channel: str, summary: str, client_nick: str | None = None
) -> None:
    """Сповістити консультантів і (для Sitniks) повісити тег готовності до підбору."""
    if lead_id in _NOTIFIED:
        return

    who = f"@{client_nick}" if client_nick else "клієнтка"
    lines = [f"💙 <b>ГОТОВА ДО ПІДБОРУ</b> — {who}", ""]
    if summary:
        lines.append(summary)
    if channel == "sitniks":
        lines.append(f'\n<a href="{_sitniks_link(lead_id)}">Відкрити чат у Sitniks →</a>')
    text = "\n".join(lines)

    # 1) Telegram-сповіщення консультанткам — опційно (окрім статусу в Sitniks)
    if settings.HANDOFF_TELEGRAM:
        try:
            from src.consultant.handoff_bot import get_notify_bot

            await get_notify_bot().send_message(
                settings.TELEGRAM_CONSULTANTS_CHAT_ID,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:  # не валимо діалог через збій сповіщення
            print(f"[handoff] tg notify failed for {lead_id}: {e}", flush=True)

    # 2) Статус у Sitniks → «🔥 Гарячий лід від Агента» (дівчата розбирають по ньому)
    if channel == "sitniks":
        try:
            from src.sitniks.client import SitniksClient

            sc = SitniksClient()
            try:
                await sc.set_chat_status(lead_id, settings.AGENT_HANDOFF_STATUS)
            finally:
                await sc.close()
        except Exception as e:
            print(f"[handoff] sitniks status failed for {lead_id}: {e}", flush=True)

    _NOTIFIED.add(lead_id)
    if len(_NOTIFIED) > 10000:
        _NOTIFIED.clear()
    print(f"[handoff] ✓ передано консультанту: {lead_id} ({channel})", flush=True)
