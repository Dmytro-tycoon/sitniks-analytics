"""Канал: агент-продавець у Sitniks (Instagram-директ, Telegram, інші джерела Sitniks).

Логіка: знаходимо чати, де останнє повідомлення — від клієнта і без відповіді →
агент генерує відповідь на основі історії чату → відправляємо через Sitniks send_message.
Коли клієнт готовий купити — повідомляємо керівника оформити замовлення (Sitniks /orders).

Запуск: python scripts/run_sitniks_seller.py  (потрібні ключі Sitniks + Claude).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from src.agent.engine import respond
from src.agent.memory import Conversation
from src.agent.playbook import get_playbook
from src.config import settings
from src.crm.base import Dialog, get_connector

POLL_SECONDS = 60


def _conv_from_dialog(dialog: Dialog) -> Conversation:
    conv = Conversation(lead_id=dialog.id, channel="sitniks")
    for m in dialog.messages:
        conv.add("client" if m.sender == "client" else "agent", m.text)
    return conv


def _needs_reply(dialog: Dialog) -> bool:
    return bool(dialog.messages) and dialog.messages[-1].sender == "client"


async def process_chat(connector, dialog: Dialog, playbook: str) -> dict | None:
    """Згенерувати й відправити відповідь у конкретний чат Sitniks."""
    conv = _conv_from_dialog(dialog)
    result = await respond(conv, playbook=playbook)
    reply = result.get("reply", "")
    if reply and not result.get("escalate"):
        await connector.send_message(dialog.id, reply)
    # TODO: result["wants_order"] → connector.create_order(...) або пінг керівнику
    # TODO: result["escalate"] → повідомити керівника, не відповідати автоматично
    return result


async def poll_once(connector) -> int:
    now = datetime.now()
    dialogs = await connector.get_dialogs(now - timedelta(days=2), now)
    playbook = get_playbook()
    handled = 0
    for d in dialogs:
        if _needs_reply(d):
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
