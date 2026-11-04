"""
Google Ads API (REST) — читання статистики кабінету SKIN.ONE.

Доступ (налаштовано 04.11.2026): OAuth-клієнт Desktop з проєкту Google Cloud hybrid-creek-157313,
refresh token акаунта з доступом до кабінету. Developer token Google більше не вимагає — рівень доступу
(Explorer) прив'язаний до Cloud-проєкту. Заголовок login-customer-id НЕ передаємо: доступ до кабінету прямий.

.env: GOOGLE_ADS_REFRESH_TOKEN, GOOGLE_ADS_CUSTOMER_ID, GOOGLE_ADS_OAUTH_CLIENT_FILE (JSON клієнта, шлях від кореня репо).
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API = "https://googleads.googleapis.com/v25"
ROOT = Path(__file__).resolve().parent.parent.parent


def _access_token() -> str:
    f = Path(os.getenv("GOOGLE_ADS_OAUTH_CLIENT_FILE", "google_ads_oauth_client.json"))
    c = json.loads((f if f.is_absolute() else ROOT / f).read_text())["installed"]
    body = urllib.parse.urlencode({
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"], "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body, timeout=60) as r:
        return json.load(r)["access_token"]


def search(query: str, customer_id: str = None) -> list:
    """GAQL-запит → список рядків (усі сторінки)."""
    cid = (customer_id or os.environ["GOOGLE_ADS_CUSTOMER_ID"]).replace("-", "")
    headers = {"Authorization": "Bearer " + _access_token(), "Content-Type": "application/json"}
    rows, token = [], None
    while True:
        body = {"query": query, **({"pageToken": token} if token else {})}
        req = urllib.request.Request(f"{API}/customers/{cid}/googleAds:search",
                                     data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.load(r)
        rows += d.get("results", [])
        token = d.get("nextPageToken")
        if not token:
            return rows


def day_totals(day: date) -> dict:
    """Сума по всіх кампаніях кабінету за день: {spend, impressions, clicks} (гривні)."""
    rows = search("SELECT metrics.cost_micros, metrics.impressions, metrics.clicks FROM campaign "
                  f"WHERE segments.date = '{day.isoformat()}'")
    m = [r.get("metrics", {}) for r in rows]
    return {
        "spend": round(sum(int(x.get("costMicros", 0)) for x in m) / 1e6, 2),
        "impressions": sum(int(x.get("impressions", 0)) for x in m),
        "clicks": sum(int(x.get("clicks", 0)) for x in m),
    }
