"""ОБОРОТНИЙ тест: чи дозволяє Sitniks Open API змінювати статус чату.

Робить: запам'ятовує поточний статус чату → пробує змінити на target → перевіряє →
ЗАВЖДИ повертає початковий статус назад (try/finally). Нічого не залишає зміненим.

⚠️ Це РЕАЛЬНИЙ запис у Sitniks. Запускати свідомо. Найкраще — на тестовому чаті:
    PYTHONPATH=. python scripts/test_status_change.py <chat_id> [target_status]

Якщо chat_id не вказано — бере найстаріший чат за останні 2 тижні (менше шансів,
що на нього зараз дивляться), але все одно оборотно.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta

from src.sitniks.client import SitniksClient


async def _status(c: SitniksClient, cid: str) -> str:
    ch = await c.get_chat(cid)
    s = ch.get("status")
    return (s.get("title") if isinstance(s, dict) else s) or ""


async def main() -> None:
    cid = sys.argv[1] if len(sys.argv) > 1 else None
    target = sys.argv[2] if len(sys.argv) > 2 else None

    c = SitniksClient()
    try:
        if not cid:
            d = await c.get_chats(datetime.now() - timedelta(days=16), datetime.now() - timedelta(days=13),
                                  limit=10, skip=0)
            chats = d.get("data", [])
            if not chats:
                print("Немає чатів у вікні — вкажи chat_id явно.")
                return
            cid = chats[0]["id"]

        orig = await _status(c, cid)
        if not target:
            target = "В роботі" if orig != "В роботі" else "Новый"
        print(f"Чат {cid}: поточний статус {orig!r} → пробуємо {target!r}")

        try:
            resp = await c.set_chat_status(cid, target)
            rs = resp.get("status") if isinstance(resp, dict) else resp
            print(f"PUT ok · у відповіді status={rs!r}")
            after = await _status(c, cid)
            print(f"GET після зміни: {after!r}  →  "
                  f"{'✅ СТАТУС ЗМІНЮЄТЬСЯ ЧЕРЕЗ API' if after == target else '❌ НЕ змінився (API ігнорує status)'}")
        finally:
            await c.set_chat_status(cid, orig)
            back = await _status(c, cid)
            print(f"Повернуто до {orig!r}: {'✓ відновлено' if back == orig else '⚠️ УВАГА: не відновлено!'}")
    finally:
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
