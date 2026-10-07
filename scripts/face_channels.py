"""Статистика skin.one.ua (обличчя) по каналах за один день → РНП День.

python scripts/face_channels.py 2026-09-22 [--write]

Без --write лише друкує таблицю. Правила каналів погоджено у вересні 2026,
оновлено 07.10.2026 (5 каналів, стовпці одразу перед стовпцем дня):
  - чати — за (ownerName, initialSource); бот SKIN-ONE Assistant → «Сайт ФБ»;
    усе, що не підпадає під канали (інші чати, замовлення без чату) → «Інстаграм»;
  - сайт — за міткою `Реклама:` у коментарі: meta → «Сайт ФБ», google → «Сайт Гугл»,
    instagram/ig (link_in_bio) → «Інстаграм»; без мітки → «Сайт прямі»;
  - день = календарна доба за Києвом; продажі/ТО/маржа без статусів з
    src/analyzer/order_status.py (як у таблиці реклами).
Пишемо рядки 40 (ТО), 42 (маржа), 45 (заявки), 46 (продажі), 47 (повторні — див.
src/analyzer/repeat_clients.py), 49 (товарів) — у 5 колонок каналів
і в колонку самого дня (сума каналів).
"""
import asyncio, re, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date, timedelta
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import settings
from src.sitniks.client import SitniksClient
from src.sheets.client import SheetsClient
from src.analyzer.order_status import is_countable_order
from src.analyzer import repeat_clients

KIEV = pytz.timezone("Europe/Kiev")
SHEET_ID = "1U-JZBWFBb-zFMpBGF-h50lFgUKtRnN5zyLkuQofiKyI"
CHANNELS = ["Інстаграм", "ФБ", "Сайт ФБ", "Сайт Гугл", "Сайт прямі"]
CHAT_CHANNEL = {  # (ownerName, initialSource) -> колонка
    ("skin.one.ua", "instagram"): "Інстаграм",
    ("Анастасія Ємець - косметолог-естетист", "facebook"): "ФБ",
    ("SKIN.ONE — косметолог онлайн", "telegram_bot"): "Інстаграм",
    ("SKIN-ONE Assistant", "telegram_bot"): "Сайт ФБ",
}
DEFAULT_CHANNEL = "Інстаграм"  # усі інші джерела (07.10.2026)
SITE_PREFIX = "Сайт skin-one.com.ua"
ROWS = {"to": 40, "margin": 42, "leads": 45, "sales": 46, "repeat": 47, "items": 49}
UAH_FORMAT = {"type": "CURRENCY", "pattern": "#,##0[$грн.]"}
MONTHS = {9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"}


def site_channel(comment: str) -> str:
    """Канал сайт-замовлення за міткою `Реклама:`."""
    m = re.search(r"Реклама:\s*([^/\s]+)", comment)
    src = (m.group(1).lower() if m else "")
    if src == "meta":
        return "Сайт ФБ"
    if src == "google":
        return "Сайт Гугл"
    if src in ("instagram", "ig"):  # link_in_bio з інстаграм-профілю
        return "Інстаграм"
    return "Сайт прямі"  # без мітки реклами


async def collect(day: date) -> dict:
    s = SitniksClient()
    a = KIEV.localize(datetime(day.year, day.month, day.day))
    b = a + timedelta(days=1)
    orders = await s.get_orders_exact(a, b)
    index = repeat_clients.load_index()
    # межі в UTC: фільтри Sitniks ігнорують часовий пояс у рядку дати
    new_chats = await s.get_all_chats(a.astimezone(pytz.utc), b.astimezone(pytz.utc), by_first_message=True)

    st = {c: defaultdict(float) for c in CHANNELS}
    new_ids = set()
    for c in new_chats:
        ch = CHAT_CHANNEL.get((c.get("ownerName"), c.get("initialSource")), DEFAULT_CHANNEL)
        st[ch]["leads"] += 1
        new_ids.add(c["id"])

    chat_cache = {}
    for o in orders:
        comment = o.get("managerComment") or ""
        if SITE_PREFIX in comment:  # менеджер може дописати нотатку на початку
            ch = site_channel(comment)
            st[ch]["leads"] += 1
        else:
            cid = o.get("chatId")
            if not cid:
                ch = DEFAULT_CHANNEL
                st[ch]["leads"] += 1
            else:
                if cid not in chat_cache:
                    chat_cache[cid] = await s.get_chat(cid)
                    await asyncio.sleep(0.3)
                chat = chat_cache[cid]
                ch = CHAT_CHANNEL.get((chat.get("ownerName"), chat.get("initialSource")), DEFAULT_CHANNEL)
                if cid not in new_ids:
                    st[ch]["leads"] += 1  # замовлення з діючого чату
        if not is_countable_order(o):
            continue
        to = float(o.get("totalPriceDiscount") or 0)
        cost = sum(float(p.get("costPrice") or 0) * float(p.get("quantity") or 1) for p in o.get("products", []))
        st[ch]["to"] += to
        st[ch]["margin"] += to - cost
        st[ch]["sales"] += 1
        st[ch]["repeat"] += repeat_clients.is_repeat(o, index)
        st[ch]["items"] += sum(float(p.get("quantity") or 1) for p in o.get("products", []))
    # покупки дня → в індекс (перші покупки нових клієнтів)
    if repeat_clients.update_index(index, orders):
        repeat_clients.save_index(index)
    return st


def write(day: date, st: dict):
    sh = SheetsClient(settings.GOOGLE_SERVICE_ACCOUNT_FILE, SHEET_ID)
    tab = f"'РНП День ({MONTHS[day.month]})'"
    hdr = sh._service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"{tab}!A38:DZ39").execute()["values"]
    dates, names = hdr[0], hdr[1]
    start = dates.index(str(day.day))
    data = []
    # Колонки каналів стоять одразу ПЕРЕД колонкою дня (BL–BP → BQ=28).
    window = list(range(start - 1, start - 1 - len(CHANNELS), -1))  # рівно 5 колонок перед днем
    for ch in CHANNELS:
        idx = next((i for i in window if 0 <= i < len(names) and names[i] == ch), None)
        if idx is None:
            raise RuntimeError(f"Не знайдено колонку «{ch}» поруч із {day}")
        col = sh._col_index_to_letter(idx)
        print(f"  {ch} → колонка {col}")
        for k, row in ROWS.items():
            v = round(st[ch][k], 2) if k in ("to", "margin") else int(round(st[ch][k]))
            data.append({"range": f"{tab}!{col}{row}", "values": [[v]]})
    # Колонка самого дня = сума каналів (ті самі рядки)
    day_col = sh._col_index_to_letter(start)
    print(f"  Разом → колонка {day_col}")
    for k, row in ROWS.items():
        total = sum(st[ch][k] for ch in CHANNELS)
        v = round(total, 2) if k in ("to", "margin") else int(round(total))
        data.append({"range": f"{tab}!{day_col}{row}", "values": [[v]]})
    sh._service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": data}).execute()

    # Гроші (рядки 40, 42) — у гривнях: скопійовані колонки бувають у форматі $
    sheet_id = next(
        x["properties"]["sheetId"]
        for x in sh._service.spreadsheets().get(spreadsheetId=SHEET_ID, fields="sheets.properties").execute()["sheets"]
        if x["properties"]["title"] == tab.strip("'")
    )
    first = start - len(CHANNELS)
    reqs = [{
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                      "startColumnIndex": first, "endColumnIndex": start + 1},
            "cell": {"userEnteredFormat": {"numberFormat": UAH_FORMAT}},
            "fields": "userEnteredFormat.numberFormat",
        }
    } for row in (ROWS["to"], ROWS["margin"])]
    sh._service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": reqs}).execute()


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1])
    st = asyncio.run(collect(day))
    print(f"{'':12}{'ТО':>10}{'Маржа':>10}{'Заявок':>8}{'Продажі':>9}{'Повт.':>7}{'Товарів':>9}")
    for ch in CHANNELS:
        d = st[ch]
        print(f"{ch:12}{d['to']:>10.2f}{d['margin']:>10.2f}{d['leads']:>8.0f}{d['sales']:>9.0f}{d['repeat']:>7.0f}{d['items']:>9.0f}")
    print(f"{'Разом':12}{sum(st[c]['to'] for c in CHANNELS):>10.2f}{sum(st[c]['margin'] for c in CHANNELS):>10.2f}"
          f"{sum(st[c]['leads'] for c in CHANNELS):>8.0f}{sum(st[c]['sales'] for c in CHANNELS):>9.0f}"
          f"{sum(st[c]['repeat'] for c in CHANNELS):>7.0f}"
          f"{sum(st[c]['items'] for c in CHANNELS):>9.0f}")
    if "--write" in sys.argv:
        write(day, st)
        print("✅ записано")
