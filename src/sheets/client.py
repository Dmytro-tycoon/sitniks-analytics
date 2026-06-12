"""Google Sheets client — читання та запис у таблицю статистики."""
import base64
import json
import logging
import os
import tempfile
from typing import Any, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Назви листів по місяцях (для автовибору)
SHEET_NAMES = {
    1: "РНП День (Січень)",
    2: "РНП День (Лютий)",
    3: "РНП День (Березень)",
    4: "РНП День (Квітень)",
    5: "РНП День (Травень)",
    6: "РНП День (Червень)",
    7: "РНП День (Липень)",
    8: "РНП День (Серпень)",
    9: "РНП День (Вересень)",
    10: "РНП День (Жовтень)",
    11: "РНП День (Листопад)",
    12: "РНП День (Грудень)",
}

# Рядки нижньої таблиці (UAH) — row index у Google Sheets (1-based)
LOWER_TABLE_ROWS = {
    "to":               40,   # ТО, грн
    "margin":           42,   # Маржа всього, грн
    "leads":            45,   # Заявок
    "sales_total":      46,   # Продажі всього, к-сть
    "sales_repeat":     47,   # Продажі повторних, к-сть
    "products_qty":     49,   # Товарів/послуг к-сть
    "fb_spend":         55,   # Рекламний бюджет, грн
    "fb_impressions":   57,   # Кол-во показів
    "fb_clicks":        58,   # Кол-во кліків
}

# Рядок 38 (нижньої таблиці) містить дати (1..30/31)
LOWER_DATE_ROW = 38


class SheetsClient:
    def __init__(self, service_account_file: str, spreadsheet_id: str):
        # Підтримка base64-encoded JSON через env змінну GOOGLE_SERVICE_ACCOUNT_B64
        b64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64", "")
        if b64:
            info = json.loads(base64.b64decode(b64).decode("utf-8"))
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            creds = service_account.Credentials.from_service_account_file(
                service_account_file, scopes=SCOPES
            )
        self._service = build("sheets", "v4", credentials=creds)
        self.spreadsheet_id = spreadsheet_id

    def _sheet_name(self, month: int) -> str:
        return SHEET_NAMES.get(month, f"РНП День (місяць {month})")

    def _get_day_column(self, month: int, day: int) -> Optional[str]:
        """Повертає літеру колонки (напр. 'C') для вказаного дня місяця."""
        sheet = self._sheet_name(month)
        result = self._service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{sheet}'!A{LOWER_DATE_ROW}:AJ{LOWER_DATE_ROW}",
        ).execute()
        row = result.get("values", [[]])[0]
        for idx, val in enumerate(row):
            if val.strip() == str(day):
                # idx 0 = колонка A, idx 1 = B, etc.
                col_letter = self._col_index_to_letter(idx)
                return col_letter
        return None

    @staticmethod
    def _col_index_to_letter(idx: int) -> str:
        """0→A, 1→B, ..., 25→Z, 26→AA, ..."""
        result = ""
        idx += 1  # 1-based
        while idx > 0:
            idx, remainder = divmod(idx - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def write_day_stats(self, month: int, day: int, stats: dict) -> bool:
        """
        Записує статистику за один день у нижню таблицю (UAH).
        stats: {
            "to": float,           # ТО грн
            "leads": int,          # Заявок
            "sales_total": int,    # Продажі всього
            "sales_repeat": int,   # Повторні (0 поки що)
            "fb_spend": float,     # Рекламний бюджет грн
            "fb_impressions": int, # Показів
            "fb_clicks": int,      # Кліків
        }
        """
        sheet = self._sheet_name(month)
        col = self._get_day_column(month, day)
        if not col:
            logger.error(f"Не знайдено колонку для дня {day} місяця {month}")
            return False

        data = []
        for key, row in LOWER_TABLE_ROWS.items():
            value = stats.get(key, 0)
            cell_range = f"'{sheet}'!{col}{row}"
            data.append({
                "range": cell_range,
                "values": [[value]],
            })

        body = {"valueInputOption": "RAW", "data": data}
        self._service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=body
        ).execute()

        logger.info(f"Записано статистику за {day}.{month:02d} у колонку {col}")
        return True
