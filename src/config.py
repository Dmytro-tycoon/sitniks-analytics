import json
from dotenv import load_dotenv
from pathlib import Path
import os

_root = Path(__file__).parent.parent
load_dotenv(_root / ".env", override=True)


class Settings:
    @property
    def SITNIKS_API_KEY(self): return os.getenv("SITNIKS_API_KEY", "")
    @property
    def SITNIKS_API_URL(self): return os.getenv("SITNIKS_API_URL", "")
    @property
    def ANTHROPIC_API_KEY(self): return os.getenv("ANTHROPIC_API_KEY", "")
    @property
    def TELEGRAM_BOT_TOKEN(self): return os.getenv("TELEGRAM_BOT_TOKEN", "")
    @property
    def TELEGRAM_LEADERSHIP_CHAT_ID(self): return int(os.getenv("TELEGRAM_LEADERSHIP_CHAT_ID") or "0")
    @property
    def TELEGRAM_MANAGERS(self): return json.loads(os.getenv("TELEGRAM_MANAGERS", "{}"))
    @property
    def TELEGRAM_SHADOW_CHAT_ID(self):
        v = os.getenv("TELEGRAM_SHADOW_CHAT_ID", "")
        return int(v) if v else None
    @property
    def SUPABASE_URL(self): return os.getenv("SUPABASE_URL", "")
    @property
    def SUPABASE_SERVICE_KEY(self): return os.getenv("SUPABASE_SERVICE_KEY", "")
    @property
    def ANALYSIS_TIMEZONE(self): return os.getenv("ANALYSIS_TIMEZONE", "Europe/Kiev")
    @property
    def DAILY_REPORT_TIME(self): return os.getenv("DAILY_REPORT_TIME", "09:00")
    @property
    def ADS_BOT_TOKEN(self): return os.getenv("ADS_BOT_TOKEN", "")
    @property
    def ADS_REPORT_CHAT_ID(self):
        v = os.getenv("ADS_REPORT_CHAT_ID", "")
        return int(v) if v else None

    # ── Nova Poshta bot ──────────────────────────────────────────────────────
    @property
    def NP_BOT_TOKEN(self): return os.getenv("NP_BOT_TOKEN", "")

    @property
    def NP_OPERATOR_CHAT_ID(self):
        v = os.getenv("NP_OPERATOR_CHAT_ID", "")
        return int(v) if v else 0

    @property
    def NP_ACCOUNTS(self) -> list:
        """JSON: [{"name": "skin.one.ua", "key": "..."}, ...]"""
        raw = os.getenv("NP_ACCOUNTS", "[]")
        try:
            return json.loads(raw)
        except Exception:
            return []


settings = Settings()
