"""«Звіт по менеджерам»: конверсія та винагорода менеджерок окремо по каналах Instagram / Facebook / Сайт.

  python scripts/managers_sheet.py create 2026-11      # створити вкладку «Листопад 26» (каркас + формули)
  python scripts/managers_sheet.py motivation          # таблиці коефіцієнтів FB і сайту на «Мотивація»
  python scripts/managers_sheet.py 2026-11-02 [--write]  # порахувати день (без --write лише друк)

Винагорода за день = 3% × (ТО Instagram × К_Instagram + ТО Facebook × К_Facebook + ТО Сайт × К_Сайт),
К — з таблиць на вкладці «Мотивація» за конверсією каналу за день (погоджено 30.10.2026).

Ліди / продажі (на менеджерку = assignedManagerName чату / відповідальна замовлення; уточнено з користувачем 30.10):
  - Instagram: нові чати skin.one.ua (джерело instagram; однойменне джерело TikTok — НЕ рахуємо)
    + замовлення з діючих чатів skin.one.ua; + замовлення без чату та з бота «SKIN.ONE — косметолог онлайн»
    (рахуються як замовлення Instagram: продаж і лід);
  - Facebook: нові чати «Анастасія Ємець - косметолог-естетист» + замовлення з діючих чатів;
  - Сайт: нові чати Viber («SKIN.ONE Viber»), Telegram («SKIN. ONE») і бота SKIN-ONE Assistant
    + замовлення з діючих чатів цих джерел; продажі — ці замовлення та замовлення з форми сайту
    (форма без чату — продаж без ліда).
  Канал замовлення визначаємо за його чатом (поле «канал продажу» в Sitniks для Instagram підписане «Tik-Tok»).
Продажі / ТО — без скасованих і неоплачених (order_status.py). День менеджерки рахуємо,
лише якщо в неї є хоча б одне замовлення (інакше в чатах «висять» перепризначені на вихідних).
"""
import asyncio
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pytz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("REPEAT_INDEX_PATH", str(Path.home() / "Documents" / "sitniks-analytics" / "data" / "client_first_purchase.json"))
from src.config import settings  # noqa: E402
from src.sitniks.client import SitniksClient  # noqa: E402
from src.sheets.client import SheetsClient  # noqa: E402
from src.analyzer.order_status import is_countable_order  # noqa: E402
from src.analyzer import repeat_clients  # noqa: E402

KIEV = pytz.timezone("Europe/Kiev")
SHEET_ID = "19RzfWqbF-SUA6-sBBj8vM4lJS5P33IJ9er3UBLpshgs"
MOTIVATION = "Мотивація"
MONTHS = {1: "Січень", 2: "Лютий", 3: "Березень", 4: "Квітень", 5: "Травень", 6: "Червень", 7: "Липень",
          8: "Серпень", 9: "Вересень", 10: "Жовтень", 11: "Листопад", 12: "Грудень"}
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"]
# Sitniks (fullname відповідальної / assignedManagerName) → назва блоку в таблиці
MANAGERS = {"Єлизавета": "Ліза", "Елизавета": "Ліза", "Діана Кириченко 2": "Діана",
            "Вікторія Тумаш 2": "Віка", "Даша": "Даша"}
BLOCKS = ["Ліза", "Діана", "Віка", "Даша"]
CHANNELS = ["Instagram", "Facebook", "Сайт"]
FB_OWNER = "Анастасія Ємець - косметолог-естетист"
IG_OWNER = "skin.one.ua"
SITE_OWNERS = {"SKIN.ONE Viber", "SKIN. ONE", "SKIN-ONE Assistant"}
SITE_PREFIX = "Сайт skin-one.com.ua"
# Таблиці коефіцієнтів на «Мотивація»: (колонка «Факт», колонка «Коефіцієнт»), рядки 3–8
COEF_COLS = {"Instagram": ("C", "D"), "Facebook": ("G", "H"), "Сайт": ("K", "L")}
NEW_TABLES = {  # погоджено 30.10.2026; Instagram — чинна таблиця B1:D8
    "Facebook": ("F", 0.08, [(0.12, 1.3), (0.10, 1.1), (0.08, 1), (0.06, 0.85), (0.04, 0.75), (0, 0.7)]),
    "Сайт": ("J", 0.60, [(0.70, 1.3), (0.65, 1.1), (0.60, 1), (0.50, 0.85), (0.40, 0.75), (0, 0.7)]),
}

# ─── Розмітка блоку менеджерки (рядки відносно початку блоку, 0-based) ─────────
BLOCK_H = 32
R_DATE, R_WD, R_NAME = 0, 1, 2
CH_ROW = {"Instagram": 3, "Facebook": 9, "Сайт": 15}     # рядок-заголовок каналу; далі +1..+5
L, S, TO, CONV, COEF = 1, 2, 3, 4, 5
R_TOTAL = 21
T_TO, T_S, T_REP, T_REP_PCT, T_ITEMS, T_PER_CHECK, T_AVG, T_3PCT, T_PAY = range(22, 31)

UAH = {"type": "NUMBER", "pattern": "#,##0 [$грн.];-#,##0 [$грн.];"}  # нулі порожніх днів не показуємо
INT = {"type": "NUMBER", "pattern": "#,##0;-#,##0;"}
PCT = {"type": "PERCENT", "pattern": "0.0%"}
DEC2 = {"type": "NUMBER", "pattern": "0.00"}
DEC1 = {"type": "NUMBER", "pattern": "#,##0.0"}


def tab_name(year, month):
    return f"{MONTHS[month]} {year % 100}"


def col(idx):  # 0-based → A1
    return SheetsClient._col_index_to_letter(idx)


def month_columns(year, month):
    """[(тип, день|номер_тижня)] для колонок E…: 7 днів пн–нд (порожні поза місяцем) + «Тиждень N»."""
    first = date(year, month, 1)
    nxt = date(year + month // 12, month % 12 + 1, 1)
    d = first - timedelta(days=first.weekday())
    cols, week = [], 0
    while d < nxt:
        week += 1
        for _ in range(7):
            cols.append(("day", d.day if d.month == month else None))
            d += timedelta(days=1)
        cols.append(("week", week))
    return cols


def channel_of_chat(chat):
    """Канал чату для лідів; None — не рахуємо як лід (TikTok, «косметолог онлайн», інші)."""
    owner, src = chat.get("ownerName"), chat.get("initialSource")
    if owner == IG_OWNER and src == "instagram":
        return "Instagram"
    if owner == FB_OWNER:
        return "Facebook"
    if owner in SITE_OWNERS:
        return "Сайт"
    return None


async def collect(day: date) -> dict:
    """{блок: {"Instagram": {L,S,TO}, …, "rep": n, "items": n}} лише для менеджерок із замовленнями дня."""
    s = SitniksClient()
    try:
        a = KIEV.localize(datetime(day.year, day.month, day.day))
        b = a + timedelta(days=1)
        orders = await s.get_orders_exact(a, b)
        chats = await s.get_all_chats(a.astimezone(pytz.utc), b.astimezone(pytz.utc), by_first_message=True)
        chat_of = {}
        for cid in {o.get("chatId") for o in orders if o.get("chatId")}:
            chat_of[cid] = await s.get_chat(cid)
            await asyncio.sleep(0.2)
    finally:
        await s.close()
    index = repeat_clients.load_index()
    res = defaultdict(lambda: {**{ch: {"L": 0, "S": 0, "TO": 0.0} for ch in CHANNELS}, "rep": 0, "items": 0})
    active = set()
    new_ids = set()
    for c in chats:
        new_ids.add(c["id"])
        m, ch = MANAGERS.get(c.get("assignedManagerName")), channel_of_chat(c)
        if m and ch:
            res[m][ch]["L"] += 1
    for o in orders:
        m = MANAGERS.get(((o.get("responsible") or {}).get("user") or {}).get("fullname"))
        if not m:
            continue
        active.add(m)
        cid = o.get("chatId")
        chat_ch = channel_of_chat(chat_of.get(cid) or {}) if cid else None
        if SITE_PREFIX in (o.get("managerComment") or ""):
            ch, lead = "Сайт", chat_ch == "Сайт" and cid not in new_ids
        elif chat_ch:
            ch, lead = chat_ch, cid not in new_ids
        else:  # без чату / «косметолог онлайн» / інші джерела — як замовлення Instagram
            ch, lead = "Instagram", True
        res[m][ch]["L"] += lead
        if is_countable_order(o):
            x = res[m][ch]
            x["S"] += 1
            x["TO"] += float(o.get("totalPriceDiscount") or 0)
            res[m]["rep"] += repeat_clients.is_repeat(o, index)
            res[m]["items"] += sum(int(p.get("quantity") or 1) for p in o.get("products") or [])
    return {m: res[m] for m in BLOCKS if m in active}


def _svc():
    return SheetsClient(settings.GOOGLE_SERVICE_ACCOUNT_FILE, SHEET_ID)._service.spreadsheets()


def has_channel_tab(day: date) -> bool:
    """Чи є вкладка місяця з новою розміткою по каналах (до листопада 2026 — старі вкладки, їх не чіпаємо)."""
    tab = tab_name(day.year, day.month)
    titles = [x["properties"]["title"] for x in
              _svc().get(spreadsheetId=SHEET_ID, fields="sheets.properties").execute()["sheets"]]
    if tab not in titles:
        return False
    b = _svc().values().get(spreadsheetId=SHEET_ID, range=f"'{tab}'!B{CH_ROW['Instagram'] + 1}").execute()
    return b.get("values") == [["Instagram"]]


def write(day: date, data: dict):
    """Пише значення дня в блоки менеджерок; менеджеркам без замовлень — очищає колонку дня."""
    svc = _svc()
    tab = tab_name(day.year, day.month)
    cols = month_columns(day.year, day.month)
    ci = 4 + next(i for i, (t, v) in enumerate(cols) if t == "day" and v == day.day)
    c = col(ci)
    first_col = svc.values().get(spreadsheetId=SHEET_ID, range=f"'{tab}'!A1:B{BLOCK_H * len(BLOCKS)}").execute()
    rows = first_col.get("values", [])
    names = [r[0] if r else "" for r in rows]
    upd = []
    for m in BLOCKS:
        if m not in names:
            raise RuntimeError(f"На вкладці «{tab}» немає блоку «{m}»")
        top = names.index(m) - R_NAME + 1  # 1-based рядок «Дата» блоку
        hdr = rows[top - 1 + CH_ROW["Instagram"]]
        if len(hdr) < 2 or hdr[1] != "Instagram":  # стара розмітка (до листопада 2026) — не пишемо
            raise RuntimeError(f"Вкладка «{tab}» не в розмітці по каналах")
        d = data.get(m)
        for ch in CHANNELS:
            r0 = top + CH_ROW[ch]
            vals = [d[ch]["L"], d[ch]["S"], round(d[ch]["TO"], 2)] if d else ["", "", ""]
            upd.append({"range": f"'{tab}'!{c}{r0 + L}:{c}{r0 + TO}", "values": [[v] for v in vals]})
        upd.append({"range": f"'{tab}'!{c}{top + T_REP}", "values": [[d["rep"] if d else ""]]})
        upd.append({"range": f"'{tab}'!{c}{top + T_ITEMS}", "values": [[d["items"] if d else ""]]})
    svc.values().batchUpdate(spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": upd}).execute()


# ─── Створення вкладки місяця ─────────────────────────────────────────────
def _rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def _coef_formula(ch, conv_ref, l_ref, s_ref):
    f, k = COEF_COLS[ch]
    parts = ";".join(f"{conv_ref}>={MOTIVATION}!${f}${r};{MOTIVATION}!${k}${r}" for r in range(3, 9))
    return f'=IF(OR(N({l_ref})>0;N({s_ref})>0);IFS({parts};TRUE;{MOTIVATION}!${k}$8);"")'


def create_month(year, month):
    svc = _svc()
    tab = tab_name(year, month)
    meta = svc.get(spreadsheetId=SHEET_ID, fields="sheets.properties").execute()["sheets"]
    if any(x["properties"]["title"] == tab for x in meta):
        raise RuntimeError(f"Вкладка «{tab}» вже існує")
    cols = month_columns(year, month)
    ncols = 4 + len(cols)
    sid = svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [{"addSheet": {"properties": {
        "title": tab, "index": len(meta) - 2,  # перед «Мотивація»
        "gridProperties": {"rowCount": BLOCK_H * len(BLOCKS) + 5, "columnCount": ncols, "frozenColumnCount": 4}}}}]}
    ).execute()["replies"][0]["addSheet"]["properties"]["sheetId"]

    week_cols = [4 + i for i, (t, _) in enumerate(cols) if t == "week"]
    day_cols = [4 + i for i, (t, v) in enumerate(cols) if t == "day"]

    def week_range(wc):  # 7 денних колонок перед тижневою
        return f"{col(wc - 7)}{{r}}:{col(wc - 1)}{{r}}"

    rows = []
    for bi, m in enumerate(BLOCKS):
        top = bi * BLOCK_H + 1
        grid = [[""] * ncols for _ in range(BLOCK_H)]
        grid[R_DATE][0], grid[R_DATE][3] = "Дата", "Всього за місяць"
        grid[R_WD][0] = "День"
        grid[R_NAME][0] = m
        for i, (t, v) in enumerate(cols):
            if t == "day":
                grid[R_DATE][4 + i] = v or ""
                grid[R_WD][4 + i] = WEEKDAYS[i % 8]
            else:
                grid[R_DATE][4 + i] = f"Тиждень {v}"

        def R(rel):
            return top + rel

        def fill_sum(rel):  # тиждень = SUM днів, місяць = SUM тижнів
            for wc in week_cols:
                grid[rel][wc] = "=SUM(" + week_range(wc).format(r=R(rel)) + ")"
            grid[rel][3] = "=" + "+".join(f"{col(wc)}{R(rel)}" for wc in week_cols)

        for ch in CHANNELS:
            h = CH_ROW[ch]
            grid[h][1] = ch
            for rel, label in ((L, "Ліди, шт."), (S, "Продажі, к-сть"), (TO, "ТО, грн."),
                               (CONV, "Конверсія, %"), (COEF, "Коефіцієнт")):
                grid[h + rel][1] = label
            for rel in (L, S, TO):
                fill_sum(h + rel)
            for ci in [3] + day_cols + week_cols:
                c = col(ci)
                lr, sr = f"{c}{R(h + L)}", f"{c}{R(h + S)}"
                grid[h + CONV][ci] = f'=IF(N({lr})>0;{sr}/{lr};IF(N({sr})>0;1;""))'
            for ci in day_cols:
                c = col(ci)
                grid[h + COEF][ci] = _coef_formula(ch, f"{c}{R(h + CONV)}", f"{c}{R(h + L)}", f"{c}{R(h + S)}")
        grid[R_TOTAL][1] = "Разом"
        for rel, label in ((T_TO, "ТО всього, грн."), (T_S, "Продажі всього, к-сть"),
                           (T_REP, "Продажі повторних, к-сть"), (T_REP_PCT, "% повторних продажів"),
                           (T_ITEMS, "Товарів/послуг, к-сть"), (T_PER_CHECK, "К-сть од. у чеку"),
                           (T_AVG, "Ср. чек, грн."), (T_3PCT, "3% від ТО, грн."),
                           (T_PAY, "Винагорода з коефіцієнтами, грн.")):
            grid[rel][1] = label
        for rel in (T_REP, T_ITEMS):
            fill_sum(rel)
        for ci in [3] + day_cols + week_cols:
            c = col(ci)
            grid[T_TO][ci] = "=" + "+".join(f"{c}{R(CH_ROW[ch] + TO)}" for ch in CHANNELS)
            grid[T_S][ci] = "=" + "+".join(f"{c}{R(CH_ROW[ch] + S)}" for ch in CHANNELS)
            s_ref = f"{c}{R(T_S)}"
            grid[T_REP_PCT][ci] = f'=IF(N({s_ref})>0;{c}{R(T_REP)}/{s_ref};"")'
            grid[T_PER_CHECK][ci] = f'=IF(N({s_ref})>0;{c}{R(T_ITEMS)}/{s_ref};"")'
            grid[T_AVG][ci] = f'=IF(N({s_ref})>0;{c}{R(T_TO)}/{s_ref};"")'
            grid[T_3PCT][ci] = f"={c}{R(T_TO)}*0,03"
        for ci in day_cols:
            c = col(ci)
            grid[T_PAY][ci] = "=0,03*(" + "+".join(
                f"{c}{R(CH_ROW[ch] + TO)}*N({c}{R(CH_ROW[ch] + COEF)})" for ch in CHANNELS) + ")"
        fill_sum(T_PAY)
        rows += grid
    svc.values().update(spreadsheetId=SHEET_ID, range=f"'{tab}'!A1", valueInputOption="USER_ENTERED",
                        body={"values": rows}).execute()

    # Оформлення в стилі попередніх місяців
    ORANGE, DARK, GREY, LIGHT, GREEN = "#E69138", "#434343", "#D9D9D9", "#F3F3F3", "#D9EAD3"
    req = []

    def rng(r1, r2, c1=0, c2=ncols):  # 0-based, r2/c2 виключно
        return {"sheetId": sid, "startRowIndex": r1, "endRowIndex": r2, "startColumnIndex": c1, "endColumnIndex": c2}

    def fmt(r, f, fields):
        req.append({"repeatCell": {"range": r, "cell": {"userEnteredFormat": f}, "fields": f"userEnteredFormat({fields})"}})

    fmt(rng(0, BLOCK_H * len(BLOCKS)), {"textFormat": {"fontFamily": "Arial", "fontSize": 10},
                                        "verticalAlignment": "MIDDLE"}, "textFormat,verticalAlignment")
    widths = [52, 100, 199, 110] + [84 if t == "day" else 95 for t, _ in cols]
    for i, w in enumerate(widths):
        req.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i,
                                                            "endIndex": i + 1}, "properties": {"pixelSize": w},
                                                  "fields": "pixelSize"}})
    for bi in range(len(BLOCKS)):
        t = bi * BLOCK_H
        white_bold = {"bold": True, "foregroundColor": _rgb("#FFFFFF")}
        fmt(rng(t, t + 2), {"backgroundColor": _rgb(ORANGE), "textFormat": {"bold": True},
                            "horizontalAlignment": "CENTER"}, "backgroundColor,textFormat,horizontalAlignment")
        fmt(rng(t + R_NAME, t + R_NAME + 1), {"backgroundColor": _rgb(DARK), "textFormat": white_bold},
            "backgroundColor,textFormat")
        fmt(rng(t + 3, t + R_TOTAL + 10, 3, 4), {"backgroundColor": _rgb(DARK), "textFormat": white_bold},
            "backgroundColor,textFormat")
        for wc in week_cols:
            fmt(rng(t + 3, t + R_TOTAL + 10, wc, wc + 1), {"backgroundColor": _rgb(GREY)}, "backgroundColor")
        for h in list(CH_ROW.values()) + [R_TOTAL]:
            fmt(rng(t + h, t + h + 1, 1, ncols), {"backgroundColor": _rgb(LIGHT), "textFormat": {"bold": True}},
                "backgroundColor,textFormat")
        fmt(rng(t + 3, t + R_TOTAL + 10, 1, 3), {"textFormat": {"bold": True}}, "textFormat")
        for h in CH_ROW.values():
            fmt(rng(t + h + L, t + h + S + 1, 3, ncols), {"numberFormat": INT}, "numberFormat")
            fmt(rng(t + h + TO, t + h + TO + 1, 3, ncols), {"numberFormat": UAH}, "numberFormat")
            fmt(rng(t + h + CONV, t + h + CONV + 1, 1, ncols), {"numberFormat": PCT, "backgroundColor": _rgb(GREEN)},
                "numberFormat,backgroundColor")
            fmt(rng(t + h + COEF, t + h + COEF + 1, 3, ncols), {"numberFormat": DEC2}, "numberFormat")
        for rel, nf in ((T_TO, UAH), (T_S, INT), (T_REP, INT), (T_REP_PCT, PCT), (T_ITEMS, INT),
                        (T_PER_CHECK, DEC1), (T_AVG, UAH), (T_3PCT, UAH), (T_PAY, UAH)):
            fmt(rng(t + rel, t + rel + 1, 3, ncols), {"numberFormat": nf}, "numberFormat")
        fmt(rng(t + T_PAY, t + T_PAY + 1, 1, ncols), {"textFormat": {"bold": True}}, "textFormat.bold")
        for rel in range(3, R_TOTAL + 10):
            req.append({"mergeCells": {"range": rng(t + rel, t + rel + 1, 1, 3), "mergeType": "MERGE_ALL"}})
    svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": req}).execute()
    print(f"Створено вкладку «{tab}» ({len(BLOCKS)} блоки, {len(day_cols)} денних колонок)")


def setup_motivation():
    """Таблиці Facebook (F1:H8) і Сайт (J1:L8) поруч із чинною таблицею Instagram (B1:D8)."""
    svc = _svc()
    data = []
    for ch, (c0, plan, rows) in NEW_TABLES.items():
        vals = [[f"Конверсія {ch}", "", ""], ["План", "Факт", "Коефіцієнт"]]
        vals += [[plan, th, k] for th, k in rows]
        data.append({"range": f"'{MOTIVATION}'!{c0}1", "values": vals})
    svc.values().batchUpdate(spreadsheetId=SHEET_ID,
                             body={"valueInputOption": "RAW", "data": data}).execute()
    sid = next(x["properties"]["sheetId"] for x in svc.get(spreadsheetId=SHEET_ID, fields="sheets.properties")
               .execute()["sheets"] if x["properties"]["title"] == MOTIVATION)
    req = []
    for c0, _, _ in NEW_TABLES.values():
        ci = ord(c0) - 65
        req.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 2, "endRowIndex": 8,
                                             "startColumnIndex": ci, "endColumnIndex": ci + 2},
                                   "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                                   "fields": "userEnteredFormat.numberFormat"}})
        req.append({"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 2,
                                             "startColumnIndex": ci, "endColumnIndex": ci + 3},
                                   "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                                   "fields": "userEnteredFormat.textFormat.bold"}})
    svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": req}).execute()
    print("Таблиці Facebook і Сайт записано на «Мотивація»")


def show(day, data):
    print(f"Менеджерки {day:%d.%m}:")
    if not data:
        print("  немає замовлень")
    for m, d in data.items():
        parts = []
        for ch in CHANNELS:
            x = d[ch]
            cv = x["S"] / x["L"] * 100 if x["L"] else 0
            parts.append(f"{ch[:4]} {x['S']}/{x['L']} ({cv:.0f}%) {x['TO']:,.0f}".replace(",", " "))
        print(f"  {m:5} " + " · ".join(parts))


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["create"]:
        y, mth = map(int, args[1].split("-"))
        create_month(y, mth)
    elif args[:1] == ["motivation"]:
        setup_motivation()
    else:
        d = date.fromisoformat(args[0])
        res = asyncio.run(collect(d))
        show(d, res)
        if "--write" in args:
            if not has_channel_tab(d):
                sys.exit(f"Немає вкладки «{tab_name(d.year, d.month)}» у розмітці по каналах (create {d:%Y-%m})")
            write(d, res)
            print("  записано")
