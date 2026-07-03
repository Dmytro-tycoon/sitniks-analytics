"""Збірка плейбука для продавця з накопиченого тон-оф-войс кращих менеджерів.

Дані беруться з таблиці tone_of_voice (її наповнює аналітик з успішних діалогів).
Якщо БД недоступна — повертаємо порожньо, агент працює на business_context.
"""
from __future__ import annotations


def get_playbook(limit: int = 20) -> str:
    try:
        from src.database.supabase_client import _db

        rows = _db().table("tone_of_voice").select("*").limit(limit).execute().data
    except Exception:
        return ""
    if not rows:
        return ""

    lines: list[str] = []
    for r in rows:
        for mv in (r.get("winning_moves") or []):
            if isinstance(mv, dict):
                lines.append(f"• Коли клієнт: {mv.get('situation', '')} → {mv.get('response', '')}")
        for ob in (r.get("objection_playbook") or []):
            if isinstance(ob, dict):
                lines.append(f"• Заперечення «{ob.get('objection', '')}» → {ob.get('best_reply', '')}")
    return "\n".join(lines[:60])
