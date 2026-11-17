"""«Дохід на заявку» по оголошеннях Instagram (кабінет Skin One new).

Дохід — з вкладки «Інстаграм» таблиці «Ефективність реклами 2» (сума замовлень
по назві оголошення за день). Витрати й заявки (почато переписок) — Meta API.
Пише вкладку «Дохід на заявку» (повністю генерується, ручних значень немає).

Сигнал — за окупністю (дохід/витрати) за 7 днів, якщо заявок ≥10, інакше за 30 днів:
  🟢 ≥2,5 · 🟡 1,8–2,49 (біля беззбитковості) · 🔴 <1,8 · ⚪ мало даних (<10 заявок).
Дохід на заявку пояснює причину: низький при дешевих заявках — нормально (FB),
низький при дорогих — заявки «не купують» (пізнавальний креатив, без пропозиції).

Запуск: python scripts/ad_chat_value.py [YYYY-MM-DD]   (за замовчуванням — вчора, Київ)
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from src.sheets.ads_sums import SHEET_NAME, _get_service, col_for_date, col_letter  # noqa: E402

SHEET_ID = "1vM6SIydglC0K0b-bZE5woq--2CK-BubXL8yfdnJqweQ"
TAB = "Дохід на заявку"
ACCOUNT = "act_903156589086283"  # Skin One new
CHAT = "onsite_conversion.messaging_conversation_started_7d"
WINDOWS = (7, 30)
GOOD, BAD, MIN_CHATS = 2.5, 1.8, 10
MSG_GOALS = {"REPLIES", "CONVERSATIONS"}

norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()


def meta_insights(since: date, until: date) -> dict:
    tok = os.environ["FB_ACCESS_TOKEN"]
    p = {"access_token": tok, "level": "ad", "limit": 500,
         "fields": "ad_id,ad_name,spend,actions,optimization_goal",
         "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()})}
    url = f"https://graph.facebook.com/v25.0/{ACCOUNT}/insights?" + urllib.parse.urlencode(p)
    out = {}
    while url:
        r = json.load(urllib.request.urlopen(url, timeout=120))
        for x in r.get("data", []):
            if x.get("optimization_goal") not in MSG_GOALS:  # лише реклама на переписку (не каталог/сайт/кліки)
                continue
            chats = sum(float(a["value"]) for a in x.get("actions", []) if a["action_type"] == CHAT)
            o = out.setdefault(norm(x["ad_name"]), {"name": x["ad_name"], "spend": 0.0, "chats": 0.0, "ids": set()})
            o["spend"] += float(x["spend"]); o["chats"] += chats; o["ids"].add(x["ad_id"])
        url = r.get("paging", {}).get("next")
    return out


MAIN_DIR = os.path.expanduser("~/Documents/ШІ/morning_tools/ads_main")


def main_csv(w: int, d_end: date) -> dict:
    """Основний кабінет (немає доступу через API): CSV з Ads Manager, рівень «Объявления»,
    файл ads_main/main_{w}d_{DDMM}.csv за останні w днів по d_end. Реклама на кліки
    (багато кліків, майже без переписок) відкидається."""
    path = os.path.join(MAIN_DIR, f"main_{w}d_{d_end:%d%m}.csv")
    if not os.path.exists(path):
        return {}
    import csv
    out = {}
    for x in csv.DictReader(open(path, encoding="utf-8-sig")):
        nm = x.get("Название объявления") or ""
        if not nm:
            continue
        f = lambda k: float(x.get(k) or 0)
        sp, ch, clk = f("Потраченная сумма (UAH)"), f("Начата переписка"), f("Клики по ссылке")
        if clk > 200 and ch < clk / 20:
            continue
        o = out.setdefault(norm(nm), {"name": nm, "spend": 0.0, "chats": 0.0, "active": False})
        o["spend"] += sp; o["chats"] += ch; o["active"] |= (x.get("Показ рекламы") == "active")
    return out


def ad_status(ids: set) -> str:
    tok = os.environ["FB_ACCESS_TOKEN"]
    url = "https://graph.facebook.com/v25.0/?" + urllib.parse.urlencode(
        {"access_token": tok, "ids": ",".join(list(ids)[:50]), "fields": "effective_status"})
    r = json.load(urllib.request.urlopen(url, timeout=60))
    st = {v.get("effective_status") for v in r.values()}
    return "активне" if "ACTIVE" in st else "вимкнене"


def sheet_revenue(svc, d_end: date, days: int) -> dict:
    rng = f"'{SHEET_NAME}'!A1:{col_letter(col_for_date(date(d_end.year, 12, 31)))}1500"
    rows = svc.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=rng,
                                           valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    cols = [col_for_date(d_end - timedelta(i)) - 1 for i in range(days) if (d_end - timedelta(i)).year == d_end.year]
    rev = {}
    for r in rows[1:]:
        if not r or not str(r[0]).strip():
            continue
        s = sum(float(r[c]) for c in cols if c < len(r) and isinstance(r[c], (int, float)))
        rev[norm(r[0])] = rev.get(norm(r[0]), 0) + s
    return rev


def signal(roas, chats):
    if chats < MIN_CHATS or roas is None:
        return "⚪ мало даних"
    return "🟢" if roas >= GOOD else ("🟡" if roas >= BAD else "🔴")


def main(d_end: date):
    svc = _get_service()
    data = {}
    main_files = []
    for w in WINDOWS:
        ins = meta_insights(d_end - timedelta(w - 1), d_end)
        rev = sheet_revenue(svc, d_end, w)
        for k, v in ins.items():
            row = data.setdefault(("new", k), {"name": v["name"], "ids": set(), "acct": "Skin One new"})
            row["ids"] |= v["ids"]
            row[w] = {"spend": v["spend"], "chats": v["chats"], "rev": rev.get(k, 0.0)}
        mc = main_csv(w, d_end)
        if mc:
            main_files.append(f"{w}д")
        for k, v in mc.items():
            row = data.setdefault(("main", k), {"name": v["name"], "acct": "Основний", "active": False})
            row["active"] |= v["active"]
            row[w] = {"spend": v["spend"], "chats": v["chats"], "rev": rev.get(k, 0.0)}
    rows = []
    for k, r in data.items():
        if r.get(30, {}).get("spend", 0) < 1:
            continue
        r["status"] = ad_status(r["ids"]) if r["acct"] == "Skin One new" else ("активне" if r["active"] else "вимкнене")
        main_part, ref_part = [], []
        for w in WINDOWS:
            m = r.get(w, {"spend": 0, "chats": 0, "rev": 0})
            ch, sp, rv = m["chats"], m["spend"], m["rev"]
            r[f"roas{w}"], r[f"ch{w}"] = (rv / sp if sp else None), ch
            main_part += [round(sp), round(rv)]
            ref_part += [int(ch), round(sp / ch) if ch else "", round(rv / ch) if ch else ""]
        use = 7 if r["ch7"] >= MIN_CHATS else 30
        sig = signal(r[f"roas{use}"], r[f"ch{use}"]) + ("" if use == 7 else " (30 дн.)")
        roas = [round(r[f"roas{w}"], 2) if r[f"roas{w}"] is not None else "" for w in WINDOWS]
        line = [r["name"], r["acct"], r["status"], sig] + roas + main_part + [""] + ref_part
        rows.append((r["status"] != "активне", -(r.get(7, {}).get("spend", 0)), -(r[30]["spend"]), line))
    rows.sort(key=lambda x: x[:3])
    hdr1 = [f"Оновлено {datetime.now(ZoneInfo('Europe/Kyiv')):%d.%m %H:%M} · дані по {d_end:%d.%m} · кабінети: Skin One new (API) + основний ("
            f"{'CSV з Ads Manager: ' + ', '.join(main_files) if main_files else 'немає CSV — не враховано'}) · "
            f"ROAS = дохід ÷ витрати; дохід = замовлення з вкладки «Інстаграм» по назві оголошення; беззбитковість ≈ 1,8"]
    hdr2 = ["Оголошення", "Кабінет", "Статус", "Сигнал (🟢 ROAS ≥2,5 · 🟡 1,8–2,49 · 🔴 <1,8; за 7 дн., або 30 дн. якщо заявок <10)",
            "ROAS 7д", "ROAS 30д", "Витрати 7д", "Дохід 7д", "Витрати 30д", "Дохід 30д",
            "Довідка →", "Заявки 7д", "Ціна заявки 7д", "Дохід/заявку 7д", "Заявки 30д", "Ціна заявки 30д", "Дохід/заявку 30д"]
    values = [hdr1, hdr2] + [x[3] for x in rows]

    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID, fields="sheets.properties").execute()
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    if TAB not in tabs:
        rep = svc.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [
            {"addSheet": {"properties": {"title": TAB, "gridProperties": {"frozenRowCount": 2, "frozenColumnCount": 1}}}}]}).execute()
        tabs[TAB] = rep["replies"][0]["addSheet"]["properties"]["sheetId"]
    svc.spreadsheets().values().clear(spreadsheetId=SHEET_ID, range=f"'{TAB}'!A1:Z2000").execute()
    svc.spreadsheets().values().update(spreadsheetId=SHEET_ID, range=f"'{TAB}'!A1", valueInputOption="RAW",
                                       body={"values": values}).execute()
    svc.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [
        {"repeatCell": {"range": {"sheetId": tabs[TAB], "startRowIndex": 1, "endRowIndex": 2},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "wrapStrategy": "WRAP"}},
                        "fields": "userEnteredFormat(textFormat,wrapStrategy)"}},
        {"updateDimensionProperties": {"range": {"sheetId": tabs[TAB], "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 360}, "fields": "pixelSize"}},
    ]}).execute()
    print(f"[ad_chat_value] {TAB}: {len(rows)} оголошень, дані по {d_end}")
    return values


if __name__ == "__main__":
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(ZoneInfo("Europe/Kyiv")).date() - timedelta(1)
    for v in main(d)[2:]:
        if v[2] == "активне":
            print(" | ".join(str(x) for x in v))
