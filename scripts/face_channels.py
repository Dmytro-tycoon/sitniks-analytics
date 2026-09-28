"""Статистика skin.one.ua (обличчя) по каналах за один день → РНП День.

python scripts/face_channels.py 2026-09-22 [--write]

Без --write лише друкує таблицю. Правила каналів погоджено у вересні 2026:
чати — за (ownerName, initialSource); сайт — за міткою `Реклама:` у коментарі.
Продажі/ТО без статусів Відмінено / Не підтверджено / Новий. Рядок 47 не заповнюємо.
"""
import asyncio, re, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, date
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import settings
from src.sitniks.client import SitniksClient
from src.sheets.client import SheetsClient

KIEV = pytz.timezone("Europe/Kiev")
SHEET_ID = "1U-JZBWFBb-zFMpBGF-h50lFgUKtRnN5zyLkuQofiKyI"
CHANNELS = ["Інстаграм", "ФБ", "Сайт ФБ", "Сайт Гугл", "Сайт прямі"]
CHAT_CHANNEL = {  # (ownerName, initialSource) -> колонка
    ("skin.one.ua", "instagram"): "Інстаграм",
    ("Анастасія Ємець - косметолог-естетист", "facebook"): "ФБ",
    ("SKIN.ONE — косметолог онлайн", "telegram_bot"): "Інстаграм",
    ("SKIN-ONE Assistant", "telegram_bot"): "Сайт прямі",
}
SITE_PREFIX = "Сайт skin-one.com.ua"
NOT_SALE = {"Відмінено", "Не підтверджено", "Новий"}
ROWS = {"to": 40, "margin": 42, "leads": 45, "sales": 46, "items": 49}
MONTHS = {9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"}


def site_channel(comment: str) -> str:
    m = re.search(r"Реклама:\s*([^/\s]+)", comment)
    src = (m.group(1).lower() if m else "")
    if src == "meta":
        return "Сайт ФБ"
    if src == "google":
        return "Сайт Гугл"
    return "Сайт прямі"  # instagram/ig link_in_bio або без мітки


async def collect(day: date) -> dict:
    s = SitniksClient()
    a = KIEV.localize(datetime(day.year, day.month, day.day, 0, 0, 0))
    b = KIEV.localize(datetime(day.year, day.month, day.day, 23, 59, 59))
    orders = await s.get_orders(a, b)
    new_chats = await s.get_all_chats(a, b, by_first_message=True)

    st = {c: defaultdict(float) for c in CHANNELS}
    new_ids = set()
    for c in new_chats:
        ch = CHAT_CHANNEL.get((c.get("ownerName"), c.get("initialSource")))
        if ch:
            st[ch]["leads"] += 1
            new_ids.add(c["id"])

    chat_cache = {}
    for o in orders:
        comment = o.get("managerComment") or ""
        status = (o.get("status") or {}).get("title", "")
        if SITE_PREFIX in comment:  # менеджер може дописати нотатку на початку
            ch = site_channel(comment)
            st[ch]["leads"] += 1
        else:
            cid = o.get("chatId")
            if not cid:
                continue
            if cid not in chat_cache:
                chat_cache[cid] = await s.get_chat(cid)
                await asyncio.sleep(0.3)
            chat = chat_cache[cid]
            ch = CHAT_CHANNEL.get((chat.get("ownerName"), chat.get("initialSource")))
            if not ch:
                continue
            if cid not in new_ids:
                st[ch]["leads"] += 1  # замовлення з діючого чату
        if status in NOT_SALE:
            continue
        to = float(o.get("totalPriceDiscount") or 0)
        cost = sum(float(p.get("costPrice") or 0) * int(p.get("quantity") or 1) for p in o.get("products", []))
        st[ch]["to"] += to
        st[ch]["margin"] += to - cost
        st[ch]["sales"] += 1
        st[ch]["items"] += sum(int(p.get("quantity") or 1) for p in o.get("products", []))
    return st


def write(day: date, st: dict):
    sh = SheetsClient(settings.GOOGLE_SERVICE_ACCOUNT_FILE, SHEET_ID)
    tab = f"'РНП День ({MONTHS[day.month]})'"
    hdr = sh._service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"{tab}!A38:DZ39").execute()["values"]
    dates, names = hdr[0], hdr[1]
    start = dates.index(str(day.day))
    data = []
    # Колонки каналів стоять одразу ПЕРЕД колонкою дня (AA–AE → AF=22);
    # для сумісності зі старою розміткою шукаємо також після неї.
    window = list(range(start - 1, start - 8, -1)) + list(range(start + 1, start + 8))
    for ch in CHANNELS:
        idx = next((i for i in window if 0 <= i < len(names) and names[i] == ch), None)
        if idx is None:
            raise RuntimeError(f"Не знайдено колонку «{ch}» поруч із {day}")
        col = sh._col_index_to_letter(idx)
        print(f"  {ch} → колонка {col}")
        for k, row in ROWS.items():
            v = round(st[ch][k], 2) if k in ("to", "margin") else int(st[ch][k])
            data.append({"range": f"{tab}!{col}{row}", "values": [[v]]})
    sh._service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": data}).execute()


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1])
    st = asyncio.run(collect(day))
    print(f"{'':12}{'ТО':>10}{'Маржа':>10}{'Заявок':>8}{'Продажі':>9}{'Товарів':>9}")
    for ch in CHANNELS:
        d = st[ch]
        print(f"{ch:12}{d['to']:>10.0f}{d['margin']:>10.0f}{d['leads']:>8.0f}{d['sales']:>9.0f}{d['items']:>9.0f}")
    if "--write" in sys.argv:
        write(day, st)
        print("✅ записано")
