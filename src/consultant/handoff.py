"""Передача діалогу від агента-консультанта живій дівчині-консультанту.

Коли агент завершив кваліфікацію (handoff=true), він:
  1) шле анкету (коротке резюме + лінк на чат + нік) у Telegram-групу консультантів;
  2) вішає тег у Sitniks (💙 ГОТОВА ДО ПІДБОРУ) — візуальний маркер у CRM.
Далі підбір засобів, ціни й оформлення робить людина.
"""
from __future__ import annotations

from src.config import settings

HANDOFF_TAG = "💙 ГОТОВА ДО ПІДБОРУ"

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

    # 1) Telegram-сповіщення консультантам
    try:
        from src.telegram_bot.bot import bot

        await bot.send_message(
            settings.TELEGRAM_CONSULTANTS_CHAT_ID,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:  # не валимо діалог через збій сповіщення
        print(f"[handoff] tg notify failed for {lead_id}: {e}", flush=True)

    # 2) Тег у Sitniks (тільки для реального CRM-чату)
    if channel == "sitniks":
        try:
            from src.sitniks.client import SitniksClient

            sc = SitniksClient()
            try:
                chat = await sc.get_chat(lead_id)
                tags = chat.get("tags") or []
                if HANDOFF_TAG not in tags:
                    await sc.update_chat_tags(lead_id, tags + [HANDOFF_TAG])
            finally:
                await sc.close()
        except Exception as e:
            print(f"[handoff] sitniks tag failed for {lead_id}: {e}", flush=True)

    _NOTIFIED.add(lead_id)
    if len(_NOTIFIED) > 10000:
        _NOTIFIED.clear()
    print(f"[handoff] ✓ передано консультанту: {lead_id} ({channel})", flush=True)
