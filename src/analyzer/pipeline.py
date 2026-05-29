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
    """Основний цикл: тягне діалоги, фільтрує, аналізує батчем, зберігає."""
    sitniks = SitniksClient()
    chats = await sitniks.get_all_chats(date_from, date_to)
    if max_chats:
        chats = chats[:max_chats]

    print(f"Отримано {len(chats)} чатів. Завантажую повідомлення...")

    # Паралельно тягнемо повідомлення для всіх чатів
    sem = asyncio.Semaphore(10)

    async def load(chat):
        async with sem:
            try:
                return chat, await sitniks.get_chat_messages(chat["id"])
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
