"""Розвідка: ЯК дівчата-консультанти відповідають на холодний запит ціни.

Клієнтки з реклами часто пишуть просто «Ціна?», «Вартість?», «Почому?». Треба відтворити
реальний шаблон відповіді менеджерів. Скрипт сканує чати Sitniks, знаходить ПЕРШИЙ
запит ціни від клієнтки і склеює відповідь менеджера (підряд його репліки після запиту).

Запуск:
    source venv/bin/activate
    PYTHONPATH=. python scripts/mine_price_replies.py [days] [max_chats] [max_examples]
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timedelta

from src.sitniks.client import SitniksClient

PRICE_RE = re.compile(
    r"(ці́?н[аиуо]|вартіст|вартост|по\s?чому|почому|скільки\s+кошт|коштує|"
    r"цен[аыу]|стоимост|скольк\w*\s+сто|прайс|price)",
    re.IGNORECASE,
)


def _is_client(m: dict) -> bool:
    return not (m.get("managerName") or "").strip()


def _text(m: dict) -> str:
    return (m.get("text") or "").strip()


def _find_first_price_pair(messages: list[dict]) -> tuple[str, str, str] | None:
    """(client_query, manager_reply, ad_title) для першого запиту ціни клієнткою."""
    for i, m in enumerate(messages):
        if not _is_client(m):
            continue
        t = _text(m)
        if not t or not PRICE_RE.search(t):
            continue
        # склеюємо підряд менеджерські репліки одразу після запиту
        reply_parts: list[str] = []
        for nxt in messages[i + 1:]:
            if _is_client(nxt):
                break
            rt = _text(nxt)
            if rt:
                reply_parts.append(rt)
        if not reply_parts:
            continue
        ad = (m.get("adInfo") or {}).get("adTitle") or ""
        return t, "\n".join(reply_parts), ad
    return None


async def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    max_chats = int(sys.argv[2]) if len(sys.argv) > 2 else 180
    max_examples = int(sys.argv[3]) if len(sys.argv) > 3 else 40

    client = SitniksClient()
    now = datetime.now()
    chats = await client.get_all_chats(now - timedelta(days=days), now)
    print(f"Чатів за {days} днів: {len(chats)} · скануємо до {max_chats}")

    examples: list[tuple[str, str, str]] = []
    scanned = 0
    for c in chats[:max_chats]:
        if len(examples) >= max_examples:
            break
        scanned += 1
        try:
            msgs = await client.get_chat_messages(c["id"])
        except Exception:
            continue
        pair = _find_first_price_pair(msgs)
        if pair:
            examples.append(pair)
    await client.close()

    print(f"Проскановано чатів: {scanned} · знайдено прикладів запиту ціни: {len(examples)}\n")
    with_ad = sum(1 for _, _, ad in examples if ad)
    print(f"З них із реклами (adInfo): {with_ad}\n")
    print("=" * 70)
    for i, (q, r, ad) in enumerate(examples, 1):
        tag = f"  [реклама: {ad}]" if ad else ""
        print(f"\n#{i}{tag}\n👤 {q}\n🤖 {r[:600]}")


if __name__ == "__main__":
    asyncio.run(main())
