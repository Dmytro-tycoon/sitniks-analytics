from supabase import create_client, Client
from src.config import settings

_client: Client = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _client


def save_analysis(data: dict):
    """Upsert аналізу діалогу (за dialog_id)"""
    return get_client().table("dialog_analyses").upsert(data, on_conflict="dialog_id").execute()


def get_analyses_by_date(date_str: str):
    return get_client().table("dialog_analyses")\
        .select("*")\
        .eq("dialog_date", date_str)\
        .execute()


def get_criteria() -> str:
    result = get_client().table("criteria").select("content").execute()
    return result.data[0]["content"] if result.data else ""


def upsert_telegram_user(chat_id: int, username: str = None, first_name: str = None,
                          last_name: str = None, chat_type: str = None, chat_title: str = None):
    from datetime import datetime, timezone
    return get_client().table("telegram_users").upsert({
        "chat_id": chat_id,
        "username": username,
        "first_name": first_name,
        "last_name": last_name,
        "chat_type": chat_type,
        "chat_title": chat_title,
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="chat_id").execute()


def list_telegram_users():
    return get_client().table("telegram_users").select("*").order("first_seen_at").execute()


def save_feedback(dialog_id: str, confirmed: bool, comment: str = None):
    from datetime import datetime, timezone
    payload = {
        "user_confirmed": confirmed,
        "user_feedback_at": datetime.now(timezone.utc).isoformat(),
    }
    if comment is not None:
        payload["user_comment"] = comment
    return get_client().table("dialog_analyses").update(payload).eq("dialog_id", dialog_id).execute()


def get_analysis(dialog_id: str):
    res = get_client().table("dialog_analyses").select("*").eq("dialog_id", dialog_id).execute()
    return res.data[0] if res.data else None


def save_daily_report(date_str: str, aggregated: dict):
    return get_client().table("daily_reports").upsert({
        "report_date": date_str,
        "aggregated_data": aggregated,
        "sent_to_telegram": True,
    }, on_conflict="report_date").execute()
