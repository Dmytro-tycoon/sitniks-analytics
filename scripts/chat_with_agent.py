"""Локальна пісочниця: переписка з агентом-консультантом прямо в терміналі.

Нуль налаштувань — не потрібен Telegram-бот. Використовує ту саму логіку, що й бойовий
канал: prompt + плейбук + картки товарів + кваліфікація + передача.

Запуск:
    cd ~/Documents/sitniks-analytics
    source venv/bin/activate
    PYTHONPATH=. python scripts/chat_with_agent.py

Команди в чаті:
    /ad <текст реклами>  — імітувати, що клієнтка прийшла з реклами (для картки на «Ціна?»)
    /reset               — почати новий діалог
    /quit                — вийти
"""
from __future__ import annotations

import asyncio
import time

from src.consultant.engine import respond
from src.consultant.memory import Conversation
from src.consultant.pacing import reply_delay_seconds
from src.consultant.playbook import get_playbook


def _new_conv() -> Conversation:
    return Conversation(lead_id="local-test", channel="telegram")


def main() -> None:
    conv = _new_conv()
    playbook = get_playbook()
    ad_title: str | None = None

    print("💬 Чат з агентом-консультантом. Напишіть повідомлення як клієнтка.")
    print("   /ad <реклама> — прийшла з реклами · /reset — новий діалог · /quit — вихід\n")

    while True:
        try:
            msg = input("Ви: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg == "/quit":
            break
        if msg == "/reset":
            conv, ad_title = _new_conv(), None
            print("— новий діалог —\n")
            continue
        if msg.startswith("/ad"):
            ad_title = msg[3:].strip() or None
            print(f"— контекст реклами: {ad_title or 'знято'} —\n")
            continue

        if conv.status == "handoff":
            print("(діалог уже передано консультанту — /reset щоб почати новий)\n")
            continue

        conv.add("client", msg)
        result = asyncio.run(respond(conv, playbook=playbook, ad_title=ad_title))

        # Передача — НЕПОМІТНА: клієнтці нічого не пишемо, лише сигнал для консультантки
        if result.get("handoff"):
            print("\n🔀 [непомітна передача — клієнтці нічого не надсилається, "
                  "далі відповідає жива консультантка]")
            print(f"📋 АНКЕТА КОНСУЛЬТАНТУ:\n   {result.get('handoff_summary')}\n")
            continue

        conv.add("agent", result.get("reply", ""))

        # «Людська» затримка (як у реальному чаті) — щоб відчути темп
        delay = reply_delay_seconds()
        if delay > 0:
            print(f"\n🤖 …друкує ({delay:.0f} с)", flush=True)
            time.sleep(delay)

        print(f"\n🤖 Консультант: {result.get('reply', '')}")
        print(
            f"   ┈ stage={result.get('stage')} · intent={result.get('client_intent')} "
            f"· handoff={result.get('handoff')} · escalate={result.get('escalate')}"
        )
        print()


if __name__ == "__main__":
    main()
