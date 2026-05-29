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


def save_daily_report(date_str: str, aggregated: dict):
    return get_client().table("daily_reports").upsert({
        "report_date": date_str,
        "aggregated_data": aggregated,
        "sent_to_telegram": True,
    }, on_conflict="report_date").execute()
