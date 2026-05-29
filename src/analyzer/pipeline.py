import asyncio
from typing import List, Dict
from datetime import datetime

from src.sitniks.client import SitniksClient
from src.sitniks.parser import format_dialog_for_claude
from src.claude.client import ClaudeAnalyzer
from src.analyzer.metrics import calculate_metrics
from src.database.supabase_client import save_analysis


async def analyze_one_chat(chat: Dict, sitniks: SitniksClient, claude: ClaudeAnalyzer) -> Dict:
    messages = await sitniks.get_chat_messages(chat["id"])

    metrics = calculate_metrics(chat, messages)
    dialog_text = format_dialog_for_claude(messages)

    qualitative = await claude.analyze_dialog(
        dialog_text=dialog_text,
        manager_name=chat.get("assignedManagerName", "Невідомо"),
        chat_status=chat.get("status", ""),
        started_at=chat.get("createdAt", ""),
    )

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

        "scores": qualitative.get("scores"),
        "overall_score": qualitative.get("overall_score"),
        "alerts": qualitative.get("alerts"),
        "strengths": qualitative.get("strengths"),
        "improvements": qualitative.get("improvements"),
        "summary": qualitative.get("summary"),
        "is_template_dialog": qualitative.get("is_template_dialog", False),
    }

    save_analysis(record)
    return record


async def analyze_period(date_from: datetime, date_to: datetime, max_chats: int = None, concurrency: int = 5):
    sitniks = SitniksClient()
    claude = ClaudeAnalyzer()

    chats = await sitniks.get_all_chats(date_from, date_to)
    if max_chats:
        chats = chats[:max_chats]

    print(f"Аналізую {len(chats)} чатів...")

    sem = asyncio.Semaphore(concurrency)
    results = []
    failed = 0

    async def with_limit(chat):
        nonlocal failed
        async with sem:
            try:
                r = await analyze_one_chat(chat, sitniks, claude)
                print(f"  ✅ {chat.get('assignedManagerName', '?')} — {r['overall_score']}/10")
                return r
            except Exception as e:
                failed += 1
                print(f"  ❌ {chat.get('id')}: {e}")
                return None

    results = await asyncio.gather(*[with_limit(c) for c in chats])
    results = [r for r in results if r is not None]

    await sitniks.close()
    print(f"\n✅ Готово: {len(results)} проаналізовано, {failed} помилок")
    return results
