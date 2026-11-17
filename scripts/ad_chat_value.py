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
    for w in WINDOWS:
        ins = meta_insights(d_end - timedelta(w - 1), d_end)
        rev = sheet_revenue(svc, d_end, w)
        for k, v in ins.items():
            row = data.setdefault(k, {"name": v["name"], "ids": set()})
            row["ids"] |= v["ids"]
            row[w] = {"spend": v["spend"], "chats": v["chats"], "rev": rev.get(k, 0.0)}
    rows = []
    for k, r in data.items():
        if r.get(30, {}).get("spend", 0) < 1:
            continue
        r["status"] = ad_status(r["ids"])
        line = [r["name"], r["status"]]
        for w in WINDOWS:
            m = r.get(w, {"spend": 0, "chats": 0, "rev": 0})
            ch, sp, rv = m["chats"], m["spend"], m["rev"]
            pc = round(rv / ch) if ch else None
            line += [round(sp), int(ch), round(sp / ch) if ch else "", round(rv), pc if pc is not None else "",
                     round(rv / sp, 2) if sp else ""]
            r[f"roas{w}"], r[f"ch{w}"] = (rv / sp if sp else None), ch
        use = 7 if r["ch7"] >= MIN_CHATS else 30
        line.append(signal(r[f"roas{use}"], r[f"ch{use}"]) + ("" if use == 7 else " (30 дн.)"))
        rows.append((r["status"] != "активне", -(r.get(7, {}).get("spend", 0)), -(r[30]["spend"]), line))
    rows.sort(key=lambda x: x[:3])
    hdr1 = [f"Оновлено {datetime.now(ZoneInfo('Europe/Kyiv')):%d.%m %H:%M} · дані по {d_end:%d.%m} · кабінет Skin One new · "
            f"дохід = замовлення з вкладки «Інстаграм» по назві оголошення"]
    hdr2 = ["Оголошення", "Статус"] + sum([[f"Витрати {w}д", f"Заявки {w}д", f"Ціна заявки {w}д", f"Дохід {w}д",
                                             f"Дохід/заявку {w}д", f"ROAS {w}д"] for w in WINDOWS], []) + \
           ["Сигнал за ROAS (🟢≥2,5 · 🟡1,8–2,49 · 🔴<1,8; 7 дн., або 30 дн. якщо заявок <10)"]
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
        if v[1] == "активне" or v[2]:
            print(" | ".join(str(x) for x in v))
