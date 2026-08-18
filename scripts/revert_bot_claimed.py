"""Повернути чати, які бот узяв («🤖 В обробці Агентом»), назад у «Новий».

Потрібно, коли бот заклеймив чати, але не зміг відповісти (напр. TikTok-відправка 500):
такі чати «застрягли» — дівчата їх не беруть (бачать «в обробці ботом»). Скрипт скидає
їм статус назад на «Новий», щоб їх розібрали менеджери.

Запуск:
    source venv/bin/activate
    PYTHONPATH=. python scripts/revert_bot_claimed.py [--dry] [target_status]
        --dry          лише показати, не міняти
        target_status  куди повертати (за замовч. «Новый»)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta

from src.config import settings
from src.sitniks.client import SitniksClient


async def main() -> None:
    dry = "--dry" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry"]
    target = args[0] if args else "Новый"
    working = settings.AGENT_WORKING_STATUS.strip().lower()

    c = SitniksClient()
    chats = []
    for skip in range(0, 600, 50):
        d = await c.get_chats(datetime.now() - timedelta(days=3), datetime.now(), limit=50, skip=skip)
        b = d.get("data", [])
        chats += b
        if not b:
            break

    stuck = [ch for ch in chats if (ch.get("status") or "").strip().lower() == working]
    print(f"Чатів у статусі «{settings.AGENT_WORKING_STATUS}»: {len(stuck)}")
    for ch in stuck:
        who = f"@{ch.get('userNickName')}"
        src = ch.get("initialSource")
        if dry:
            print(f"  [dry] {who} ({src}) → {target!r}")
            continue
        try:
            await c.set_chat_status(ch["id"], target)
            print(f"  ✓ {who} ({src}) → {target!r}")
        except Exception as e:
            print(f"  ✗ {who}: {e}")
    await c.close()
    if dry:
        print("\n(dry-run — нічого не змінено; прибери --dry, щоб застосувати)")


if __name__ == "__main__":
    asyncio.run(main())
