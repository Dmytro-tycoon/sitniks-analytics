"""Прогін агента-консультанта на РЕАЛЬНИХ діалогах Sitniks (dry-run, нічого не відправляє).

Бере справжні чати обраного джерела (напр. tiktok), відтворює повідомлення клієнтки
одне за одним через агента й показує, що б він відповів. Реальні відповіді менеджера
ігноруються — ми оцінюємо саме агента.

Запуск:
    source venv/bin/activate
    PYTHONPATH=. python scripts/replay_dialogs.py [source] [n_dialogs] [max_turns]
        source     initialSource (за замовч. tiktok)
        n_dialogs  скільки діалогів прогнати (за замовч. 4)
        max_turns  макс. реплік клієнтки на діалог (за замовч. 6)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta

from src.consultant.engine import respond
from src.consultant.memory import Conversation
from src.consultant.playbook import get_playbook
from src.sitniks.client import SitniksClient


def _is_client(m: dict, client_id: str | None = None) -> bool:
    """Клієнт = sentBy збігається з userId клієнта чату (надійно навіть без managerName)."""
    sent_by = (m.get("sentBy") or "").strip()
    if client_id and sent_by:
        return sent_by == client_id
    return not (m.get("managerName") or "").strip()


def _text(m: dict) -> str:
    return (m.get("text") or "").strip()


async def _replay_one(idx: int, chat: dict, msgs: list[dict], playbook: str, max_turns: int) -> bool:
    cid = chat.get("userId")
    client_msgs = [_text(m) for m in msgs if _is_client(m, cid) and _text(m)][:max_turns]
    if not client_msgs:
        return False  # чат ініційований компанією, клієнт ще не відповів — нема на що реагувати
    # У Sitniks TikTok немає adInfo → ad_title=None (агент так само працюватиме в бою)
    ad = (chat.get("initialSource") or "?")
    print(f"\n{'#'*60}\n# ДІАЛОГ {idx} · джерело: {ad} · @{chat.get('userNickName','?')}")
    conv = Conversation(lead_id=str(chat["id"]), channel="sitniks")
    for cm in client_msgs:
        conv.add("client", cm)
        r = await respond(conv, playbook=playbook, ad_title=None)
        print(f"\n👤 {cm}")
        if r.get("handoff"):
            print("🔀 [непомітна передача консультанту]")
            print(f"   📋 {r.get('handoff_summary')}")
            break
        print(f"🤖 {r.get('reply','')}")
        print(f"   ┈ stage={r.get('stage')} handoff={r.get('handoff')} escalate={r.get('escalate')}")
        conv.add("agent", r.get("reply", ""))
    return True


async def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "tiktok"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    max_turns = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    client = SitniksClient()
    chats: list[dict] = []
    for skip in range(0, 600, 50):
        d = await client.get_chats(datetime.now() - timedelta(days=14), datetime.now(), limit=50, skip=skip)
        batch = d.get("data", [])
        chats += batch
        if not batch:
            break
    picked = [ch for ch in chats if (ch.get("initialSource") or "") == source]
    print(f"Джерело '{source}': кандидатів {len(picked)} · шукаємо {n} з реальним діалогом клієнта")

    playbook = get_playbook()
    done = 0
    for ch in picked:
        if done >= n:
            break
        try:
            msgs = await client.get_chat_messages(ch["id"])
        except Exception:
            continue
        if await _replay_one(done + 1, ch, msgs, playbook, max_turns):
            done += 1
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
