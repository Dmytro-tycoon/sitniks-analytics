"""
Google Sheets writer для сум замовлень по рекламних постах.

Схема таблиці (лист "Аркуш1" у Sheet ID = ADS_SHEET_ID):
    A: Реклама (adTitle)
    B: Всього ₴ (формула =SUM(C{row}:NV{row}))
    C: Січень (label)
    D..AH: 01.01, 02.01, ..., 31.01
    AI: Лютий (label)
    ...
    Всього 12 місяців × 32 колонки (1 label + 31 дат) = 384 колонки + 2 = 386.

Для кожного дня cron-job (з ads_bot):
    1. Отримує суми по adTitle зі свіжого build_ad_report(exclude_reported=False)
    2. Для кожної нової реклами — додає новий рядок у кінці
    3. Для кожної існуючої реклами — оновлює клітинку [row × col_for_date]
    4. Оновлює формулу в B{row}
"""
import base64
import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Dict, Optional

import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
KIEV_TZ = pytz.timezone("Europe/Kiev")

MONTHS_UA = [
    "Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
    "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень",
]

SHEET_NAME = "Аркуш1"
YEAR = 2026  # Поки хардкод, потім розширимо на 2027 коли треба

# Колонки: A=1(Реклама), B=2(Всього), далі 12*(1 label + 31 дат)
LAST_COL_INDEX = 2 + 12 * 32  # = 386
TOTAL_FORMULA_END_COL = "NV"  # = col_letter(386)


def col_letter(n: int) -> str:
    """1 → 'A', 26 → 'Z', 27 → 'AA', 386 → 'NV'."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_for_date(d: date) -> int:
    """1-based col для конкретної дати. 01.01 → 4, 31.01 → 34, 01.02 → 36 і т.д."""
    return 3 + (d.month - 1) * 32 + d.day


def _get_service():
    b64 = os.getenv("GOOGLE_SERVICE_ACCOUNT_B64", "")
    if b64:
        info = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "google-service-account.json")
        creds = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds)


class AdsSumsSheet:
    def __init__(self, spreadsheet_id: str):
        self.spreadsheet_id = spreadsheet_id
        self.service = _get_service()

    # ----- Ініціалізація / структура -----

    def _get_sheet_id_and_size(self) -> tuple:
        """Повертає (sheetId, rowCount, colCount) для SHEET_NAME."""
        meta = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
        for sh in meta.get("sheets", []):
            p = sh.get("properties", {})
            if p.get("title") == SHEET_NAME:
                gp = p.get("gridProperties", {})
                return p.get("sheetId"), gp.get("rowCount", 1000), gp.get("columnCount", 26)
        raise RuntimeError(f"Sheet {SHEET_NAME!r} not found in spreadsheet")

    def ensure_capacity(self):
        """Розширює лист до потрібної к-сті колонок (386)."""
        sheet_id, rows, cols = self._get_sheet_id_and_size()
        if cols >= LAST_COL_INDEX:
            return
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={
                "requests": [{
                    "appendDimension": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "length": LAST_COL_INDEX - cols,
                    }
                }]
            },
        ).execute()
        logger.info(f"[ads_sheet] expanded to {LAST_COL_INDEX} cols")

    def ensure_header(self):
        """Заповнює заголовок (row 1), якщо порожній або неправильний."""
        # Читаємо A1
        r = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SHEET_NAME}!A1:B1",
        ).execute()
        current = r.get("values", [[]])[0] if r.get("values") else []
        if current and current[:2] == ["Реклама", "Всього ₴"]:
            return  # вже готово

        header = ["Реклама", "Всього ₴"]
        for m in range(1, 13):
            header.append(MONTHS_UA[m - 1])
            for day in range(1, 32):
                header.append(f"{day:02d}.{m:02d}")

        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SHEET_NAME}!A1:{col_letter(len(header))}1",
            valueInputOption="USER_ENTERED",
            body={"values": [header]},
        ).execute()
        logger.info("[ads_sheet] header written")

    # ----- Основна логіка -----

    def _read_ad_rows(self) -> Dict[str, int]:
        """Читає col A (від row 2), повертає {adTitle: row_number}."""
        r = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SHEET_NAME}!A2:A5000",
        ).execute()
        rows = r.get("values", [])
        return {r[0]: i + 2 for i, r in enumerate(rows) if r and r[0]}

    def _append_ads(self, ad_titles: list) -> Dict[str, int]:
        """Додає нові рядки в кінець, повертає {adTitle: row_number}."""
        if not ad_titles:
            return {}
        existing = self._read_ad_rows()
        next_row = max(existing.values(), default=1) + 1
        values = [[t] for t in ad_titles]
        self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SHEET_NAME}!A{next_row}:A{next_row + len(ad_titles) - 1}",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        return {t: next_row + i for i, t in enumerate(ad_titles)}

    def write_day(self, target_date: date, sums_by_ad: Dict[str, float]):
        """
        Основний метод: пише суми по кожній рекламі в клітинку [row × col(target_date)].

        sums_by_ad: {adTitle: сума ₴}
        Якщо реклами ще нема в таблиці — додає новий рядок.
        Оновлює також формулу в B{row}.

        ВАЖЛИВО: якщо у клітинці цього дня для реклами, якої немає у sums_by_ad,
        уже було значення (напр. після reattribute атрибуція змінилась) — воно
        обнуляється, щоб уникнути "дублювань" по датах.
        """
        self.ensure_capacity()
        self.ensure_header()

        row_map = self._read_ad_rows()
        new_titles = [t for t in sums_by_ad if t not in row_map]
        if new_titles:
            new_rows = self._append_ads(new_titles)
            row_map.update(new_rows)

        col_idx = col_for_date(target_date)
        col_str = col_letter(col_idx)

        # 1. Читаємо поточні значення в стовпці цієї дати — щоб знайти реклами,
        # у яких було значення, але у свіжому звіті їх нема (треба очистити)
        current = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=f"{SHEET_NAME}!{col_str}2:{col_str}5000",
        ).execute().get("values", [])

        updates = []
        touched_rows = set()

        # 2. Пишемо нові суми (upsert)
        for title, amount in sums_by_ad.items():
            row = row_map[title]
            updates.append({
                "range": f"{SHEET_NAME}!{col_str}{row}",
                "values": [[round(float(amount), 2)]],
            })
            touched_rows.add(row)

        # 3. Обнуляємо реклами, які мали значення, але у свіжому звіті їх нема
        cleared = 0
        for i, cell in enumerate(current):
            row = i + 2
            if row in touched_rows:
                continue
            v = cell[0] if cell else ""
            try:
                if v != "" and float(str(v).replace(",", ".")) != 0:
                    updates.append({
                        "range": f"{SHEET_NAME}!{col_str}{row}",
                        "values": [[""]],
                    })
                    cleared += 1
            except (ValueError, TypeError):
                continue

        # 4. Оновлюємо формулу "Всього" для всіх торкнутих рядків
        for title in sums_by_ad:
            row = row_map[title]
            updates.append({
                "range": f"{SHEET_NAME}!B{row}",
                "values": [[f"=SUM(C{row}:{TOTAL_FORMULA_END_COL}{row})"]],
            })

        if not updates:
            logger.info(f"[ads_sheet] {target_date}: nothing to update")
            return

        self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": updates},
        ).execute()
        logger.info(
            f"[ads_sheet] {target_date}: wrote {len(sums_by_ad)} ads to col {col_str}, "
            f"cleared {cleared} stale cells"
        )


# ----- Публічна функція для cron -----

async def write_daily_sums_to_sheet(target_date: Optional[date] = None) -> Dict:
    """
    Викликається з cron-job. За замовчуванням пише за вчорашній день (Київ).
    Групує ВСІ замовлення за день по adTitle (без exclude_reported, щоб не залежати від інших job-ів).
    """
    from src.analyzer.ad_analytics import build_ad_report
    from src.config import settings

    sheet_id = os.getenv("ADS_SHEET_ID") or getattr(settings, "ADS_SHEET_ID", "")
    if not sheet_id:
        print("[ads_sheet] ADS_SHEET_ID не задано — пропускаю запис у таблицю")
        return {"skipped": True}

    if target_date is None:
        target_date = (datetime.now(KIEV_TZ) - timedelta(days=1)).date()

    date_from = KIEV_TZ.localize(datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0))
    date_to = date_from + timedelta(days=1)

    from src.analyzer.ad_analytics import NO_AD_LABEL

    report = await build_ad_report(date_from, date_to)
    sums = dict(report.get("sums", {}))

    # За побажанням: суми зі "Старої атрибуції" (контакт з рекламою >30 днів
    # до замовлення) — вважаємо еквівалентом прямих замовлень і додаємо
    # до "Без реклами (прямі)".
    stale_total_sum = float(report.get("stale_total_sum", 0) or 0)
    if stale_total_sum:
        sums[NO_AD_LABEL] = sums.get(NO_AD_LABEL, 0) + stale_total_sum

    sheet = AdsSumsSheet(sheet_id)
    sheet.write_day(target_date, sums)

    return {
        "date": target_date.isoformat(),
        "ads_written": len(sums),
        "total_sum": report.get("total_sum", 0) + stale_total_sum,
        "stale_added_to_direct": stale_total_sum,
    }
