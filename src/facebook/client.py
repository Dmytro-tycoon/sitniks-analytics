"""Facebook Marketing API client — отримання статистики рекламних об'яв."""
import aiohttp
import asyncio
from datetime import date
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

FB_API_VERSION = "v25.0"
FB_BASE_URL = f"https://graph.facebook.com/{FB_API_VERSION}"


class FacebookAdsClient:
    def __init__(self, access_token: str, ad_account_id: str):
        self.token = access_token
        self.account_id = ad_account_id  # наприклад "act_1147671684177345"

    async def get_insights(self, date_from: date, date_to: date) -> Dict:
        """
        Повертає агреговану статистику по рекламному акаунту за вказаний період.
        Повертає: {"spend": float, "impressions": int, "inline_link_clicks": int}
        """
        url = f"{FB_BASE_URL}/{self.account_id}/insights"
        params = {
            "fields": "spend,impressions,inline_link_clicks",
            "time_range": f'{{"since":"{date_from.isoformat()}","until":"{date_to.isoformat()}"}}',
            "level": "account",
            "access_token": self.token,
        }

        last_error = None
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        data = await resp.json()
                        if "error" in data:
                            err = data["error"]
                            last_error = err
                            # Transient errors → retry
                            if err.get("is_transient") or err.get("code") in (1, 2, 4, 17, 32, 613):
                                logger.warning(f"FB API transient error (attempt {attempt+1}): {err.get('message')}")
                                if attempt < 2:
                                    await asyncio.sleep(2 ** attempt)
                                    continue
                            raise RuntimeError(f"FB API error: {err}")
                        items = data.get("data", [])
                        if not items:
                            # Це нормальна ситуація — за цей день не було показів
                            return {"spend": 0.0, "impressions": 0, "inline_link_clicks": 0}
                        row = items[0]
                        return {
                            "spend": float(row.get("spend", 0)),
                            "impressions": int(row.get("impressions", 0)),
                            "inline_link_clicks": int(row.get("inline_link_clicks", 0)),
                        }
            except RuntimeError:
                raise
            except Exception as e:
                last_error = e
                logger.warning(f"FB API attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError(f"FB API failed after 3 attempts: {last_error}")
