"""Канал: агент-консультант у Sitniks (Instagram-директ та інші джерела Sitniks).

Логіка: знаходимо чати, де останнє повідомлення — від клієнта і без відповіді →
агент веде кваліфікацію на основі історії чату → відправляємо відповідь через Sitniks.
Коли зібрано інформацію для підбору (handoff) — передаємо діалог живому консультанту
(тег у Sitniks + анкета в Telegram-групу), агент більше не відповідає в цьому чаті.

Запуск: python scripts/run_sitniks_seller.py  (потрібні ключі Sitniks + Claude).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from src.consultant.engine import respond
from src.consultant.handoff import deliver_handoff
from src.consultant.memory import Conversation
from src.consultant.playbook import get_playbook
from src.consultant.pricecards import is_price_question
from src.config import settings
from src.crm.base import Dialog, get_connector
from src.sitniks.client import SitniksClient

POLL_SECONDS = 60


def _conv_from_dialog(dialog: Dialog) -> Conversation:
    conv = Conversation(lead_id=dialog.id, channel="sitniks")
    for m in dialog.messages:
        conv.add("client" if m.sender == "client" else "agent", m.text)
    return conv


def _needs_reply(dialog: Dialog) -> bool:
    return bool(dialog.messages) and dialog.messages[-1].sender == "client"


def _already_handed_off(dialog: Dialog) -> bool:
    """Чат уже передано людині (має тег) — агент більше не втручається."""
    from src.consultant.handoff import HANDOFF_TAG

    tags = (dialog.raw or {}).get("tags") or [] if dialog.raw else []
    return HANDOFF_TAG in tags


async def process_chat(connector, dialog: Dialog, playbook: str) -> dict | None:
    """Згенерувати й відправити відповідь у конкретний чат Sitniks, за потреби — передати."""
    conv = _conv_from_dialog(dialog)

    # На запит ціни підтягуємо заголовок реклами → правильна картка товару
    ad_title = None
    if is_price_question(conv.last_client_message()):
        try:
            sc = SitniksClient()
            try:
                ad = await sc.get_ad_info_for_chat(dialog.id)
            finally:
                await sc.close()
            ad_title = (ad or {}).get("adTitle")
        except Exception:
            pass

    result = await respond(conv, playbook=playbook, ad_title=ad_title)
    reply = result.get("reply", "")

    # Клієнтці завжди шлемо репліку (місток при передачі теж іде клієнтці),
    # окрім ескалації — там веде людина, автовідповідь може нашкодити.
    if reply and not result.get("escalate"):
        await connector.send_message(dialog.id, reply)

    # Готова до підбору → передаємо живому консультанту (тег + анкета)
    if result.get("handoff"):
        nick = (dialog.raw or {}).get("userNickName") if dialog.raw else None
        await deliver_handoff(dialog.id, "sitniks", result.get("handoff_summary") or "", nick)

    return result


async def poll_once(connector) -> int:
    now = datetime.now()
    dialogs = await connector.get_dialogs(now - timedelta(days=2), now)
    playbook = get_playbook()
    handled = 0
    for d in dialogs:
        if _needs_reply(d) and not _already_handed_off(d):
            await process_chat(connector, d, playbook)
            handled += 1
    return handled


async def run() -> None:
    connector = get_connector(settings.crm_provider)
    print("Агент-продавець запущено (Sitniks).")
    try:
        while True:
            handled = await poll_once(connector)
            print(f"[seller] оброблено чатів: {handled}")
            await asyncio.sleep(POLL_SECONDS)
    finally:
        await connector.close()


if __name__ == "__main__":
    asyncio.run(run())
