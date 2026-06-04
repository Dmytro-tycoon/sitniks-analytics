import asyncio
from typing import List, Dict
from datetime import datetime

from src.sitniks.client import SitniksClient
from src.sitniks.parser import format_dialog_for_claude
from src.claude.batch import ClaudeBatchAnalyzer
from src.analyzer.metrics import calculate_metrics
from src.analyzer.filter import should_analyze
from src.database.supabase_client import save_analysis


def build_record(chat: Dict, messages: List[Dict], metrics: Dict, qualitative: Dict = None, skip_reason: str = None) -> Dict:
    """Будуємо запис для Supabase. qualitative=None для skip-діалогів."""
    record = {
        "dialog_id": chat["id"],
        "dialog_date": chat.get("createdAt", "")[:10],
        "manager_name": chat.get("assignedManagerName", "Невідомо"),
        "client_username": chat.get("userNickName"),
        "client_name": chat.get("userName"),
        "has_order": metrics["has_order"],
        "initial_source": chat.get("initialSource"),
        "chat_status": chat.get("status"),

        "messages_count": metrics["messages_count"],
        "messages_from_manager": metrics["messages_from_manager"],
        "avg_response_minutes": metrics["response_times"]["avg"],
        "max_response_minutes": metrics["response_times"]["max"],
        "first_response_minutes": metrics["response_times"]["first"],
        "duration_minutes": metrics["duration_minutes"],
    }
    if qualitative:
        record.update({
            "scores": qualitative.get("scores"),
            "overall_score": qualitative.get("overall_score"),
            "alerts": qualitative.get("alerts"),
            "strengths": qualitative.get("strengths"),
            "improvements": qualitative.get("improvements"),
            "summary": qualitative.get("summary"),
            "is_template_dialog": qualitative.get("is_template_dialog", False),
        })
    else:
        record.update({
            "scores": None,
            "overall_score": None,
            "alerts": [],
            "strengths": [],
            "improvements": [],
            "summary": f"[SKIP: {skip_reason}] діалог не аналізовано",
            "is_template_dialog": False,
        })
    return record


async def analyze_period(date_from: datetime, date_to: datetime, max_chats: int = None):
    """Основний цикл: тягне нові чати + чати-з-замовленням, фільтрує, аналізує батчем, зберігає."""
    sitniks = SitniksClient()

    # 1. Нові чати (firstMessage у вікні) - як Sitniks показує "Нові"
    new_chats = await sitniks.get_all_chats(date_from, date_to, by_first_message=True)
    new_chat_ids = {c["id"] for c in new_chats}
    print(f"Нових чатів (firstMessage window): {len(new_chats)}")

    # 2. Замовлення за день - беремо chatId-и які не входять у новi
    orders = await sitniks.get_orders(date_from, date_to)
    existing_with_order_ids = {o["chatId"] for o in orders if o.get("chatId") and o["chatId"] not in new_chat_ids}
    print(f"Замовлень {len(orders)}, з них з ДІЮЧИХ чатів: {len(existing_with_order_ids)}")

    # 3. Тягнемо деталі діючих чатів з замовленням (послідовно щоб не впертися в rate limit)
    existing_chats = []
    for cid in existing_with_order_ids:
        try:
            c = await sitniks.get_chat(cid)
            if c:
                existing_chats.append(c)
            await asyncio.sleep(0.2)
        except Exception as e:
            print(f"❌ chat {cid}: {e}")

    chats = new_chats + existing_chats
    if max_chats:
        chats = chats[:max_chats]
    print(f"Усього на аналіз: {len(chats)} (нові: {len(new_chats)} + діючі з замовленням: {len(existing_chats)})")

    # Послідовно тягнемо повідомлення з затримкою — Sitniks rate-limit'ить агресивно
    sem = asyncio.Semaphore(2)

    async def load(chat):
        async with sem:
            try:
                msgs = await sitniks.get_chat_messages(chat["id"])
                await asyncio.sleep(0.15)
                return chat, msgs
            except Exception as e:
                print(f"❌ {chat['id']}: {e}")
                return chat, None

    loaded = await asyncio.gather(*[load(c) for c in chats])
    await sitniks.close()

    # Фільтруємо
    batch_items = []
    skipped_records = []
    chat_data = {}  # chat_id -> (chat, messages, metrics)

    for chat, messages in loaded:
        if messages is None:
            continue

        metrics = calculate_metrics(chat, messages)
        chat_data[chat["id"]] = (chat, messages, metrics)

        ok, reason = should_analyze(messages)
        if not ok:
            skipped_records.append(build_record(chat, messages, metrics, skip_reason=reason))
            continue

        batch_items.append({
            "custom_id": chat["id"],
            "manager_name": chat.get("assignedManagerName", "Невідомо"),
            "chat_status": chat.get("status", ""),
            "started_at": chat.get("createdAt", ""),
            "dialog_text": format_dialog_for_claude(messages),
        })

    print(f"✅ До аналізу: {len(batch_items)} | Пропущено: {len(skipped_records)}")

    # Зберігаємо пропущені
    for rec in skipped_records:
        try:
            save_analysis(rec)
        except Exception as e:
            print(f"❌ save skip {rec['dialog_id']}: {e}")

    if not batch_items:
        print("Нема що аналізувати")
        return []

    # Відправляємо batch і чекаємо
    batch = ClaudeBatchAnalyzer()
    results = await batch.analyze_batch(batch_items)

    # Зберігаємо
    saved = 0
    for chat_id, qualitative in results.items():
        if qualitative is None:
            continue
        chat, messages, metrics = chat_data[chat_id]
        rec = build_record(chat, messages, metrics, qualitative=qualitative)
        try:
            save_analysis(rec)
            saved += 1
        except Exception as e:
            print(f"❌ save {chat_id}: {e}")

    print(f"\n✅ Збережено: {saved} аналізів + {len(skipped_records)} skip-записів")
    return saved
