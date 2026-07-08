import json
from functools import lru_cache
from dotenv import load_dotenv
from pathlib import Path
import os

_root = Path(__file__).parent.parent
load_dotenv(_root / ".env", override=True)


@lru_cache(maxsize=4)
def _load_client_yaml(name: str) -> dict:
    """Читає clients/<name>.yaml. Ліниво, не падає якщо файлу немає."""
    path = _root / "clients" / f"{name}.yaml"
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


@lru_cache(maxsize=4)
def _load_client_context(name: str) -> str:
    """Читає clients/<name>.context.md. Порожньо якщо файлу немає."""
    path = _root / "clients" / f"{name}.context.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


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
    def NP_OPERATOR_CHAT_IDS(self) -> list:
        """Список chat_id операторів через кому. Якщо порожній — fallback на NP_OPERATOR_CHAT_ID."""
        raw = os.getenv("NP_OPERATOR_CHAT_IDS", "")
        if raw:
            return [int(x.strip()) for x in raw.split(",") if x.strip()]
        return [self.NP_OPERATOR_CHAT_ID] if self.NP_OPERATOR_CHAT_ID else []

    @property
    def NP_ACCOUNTS(self) -> list:
        """JSON: [{"name": "skin.one.ua", "key": "..."}, ...]"""
        raw = os.getenv("NP_ACCOUNTS", "[]")
        try:
            return json.loads(raw)
        except Exception:
            return []


    # ── Stats / Google Sheets ────────────────────────────────────────────────
    @property
    def FB_ACCESS_TOKEN(self): return os.getenv("FB_ACCESS_TOKEN", "")

    @property
    def GOOGLE_SERVICE_ACCOUNT_FILE(self):
        return os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE",
                         str(_root / "google-service-account.json"))

    @property
    def HAIR_STATS_SPREADSHEET_ID(self):
        return os.getenv("HAIR_STATS_SPREADSHEET_ID",
                         "1WUI5RYPXH9Dghq2L2OthjKug4cJjK1p9e_qcs2ujBpA")

    @property
    def ADS_SHEET_ID(self):
        return os.getenv("ADS_SHEET_ID",
                         "1vM6SIydglC0K0b-bZE5woq--2CK-BubXL8yfdnJqweQ")

    # ── Multi-tenant client config (з sales-agent) ──────────────────────
    @property
    def client_name(self) -> str:
        return os.getenv("CLIENT", "skin_one")

    @property
    def client(self) -> dict:
        return _load_client_yaml(self.client_name)

    @property
    def niche(self) -> str:
        return (self.client.get("client") or {}).get("niche", "продажів")

    @property
    def language(self) -> str:
        return (self.client.get("client") or {}).get("language", "uk")

    @property
    def timezone(self) -> str:
        return (self.client.get("client") or {}).get("timezone", "Europe/Kiev")

    @property
    def crm_provider(self) -> str:
        return (self.client.get("crm") or {}).get("provider", "sitniks")

    @property
    def models(self) -> dict:
        return self.client.get("models") or {
            "analysis": "claude-sonnet-4-6",
            "rag":      "claude-sonnet-4-6",
            "reply":    "claude-sonnet-4-6",
        }

    @property
    def criteria(self) -> str:
        return self.client.get("criteria", "")

    @property
    def business_context(self) -> str:
        """Бізнес-контекст з clients/<name>.context.md — підмішується в промпти."""
        return _load_client_context(self.client_name)

    # Sales bot (окремий автопілот, поки не використовується активно)
    @property
    def TELEGRAM_SALES_BOT_TOKEN(self):
        return os.getenv("TELEGRAM_SALES_BOT_TOKEN", "")


settings = Settings()
