"""Окупність по оголошеннях → стовпчики B..F вкладок «Інстаграм» і «Сайт» («Ефективність реклами 2»).

B Кабінет · C Статус · D Сигнал · E Окупність 7 днів · F Окупність 30 днів  (вікно закінчується днем d_end).

Окупність = маржа ÷ витрати (метрика власника, 28.11.2026). Маржа = дохід оголошення × маржинальність
каналу за те саме вікно з РНП («Рука на пульсі», рядки 40 ТО і 42 маржа): «Інстаграм» — канали
Інстаграм+ФБ, «Сайт» — Сайт ФБ+Сайт Гугл+Сайт прямі. Дохід — суми з сітки дат цієї ж вкладки.
Наближення: для акційних оголошень реальна маржа нижча за середню каналу.
Витрати:
  «Інстаграм» — реклама на переписку (optimization_goal REPLIES/CONVERSATIONS):
      Skin One new — Meta API; основний кабінет — CSV з Ads Manager
      (ads_main/main_{7,30}d_DDMM.csv, рівень «Объявления»; без CSV — не враховано).
      Зв'язок — назва оголошення = мітка рядка.
  «Сайт» — мітка «meta / <кампанія> / <ID групи/оголошення> / … (fbclid)»: витрати Skin One new
      по цьому ID (група оголошень, оголошення або кампанія); «… (gclid)» — увесь Google Ads.
      Мітки без ID / без реклами (прямі, link_in_bio, бот…) — порожньо.
Сигнал (за 7 днів; якщо витрат за 7 днів < MIN_SPEND — за 30 днів), «м'які» пороги для окремого
оголошення (таблиця бачить лише ~55–60% продажів реклами; пороги каналу — у РНП: IG/FB ≥2,5, сайт ≥1,5):
  Інстаграм: 🟢 ≥ 1,6 · 🟡 1,0–1,6 · 🔴 < 1,0;  Сайт: 🟢 ≥ 1,2 · 🟡 0,8–1,2 · 🔴 < 0,8 · ⚪ мало даних.

Запуск: python scripts/ad_chat_value.py [YYYY-MM-DD]   (за замовчуванням — вчора, Київ)
"""
import csv
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
from src.sheets.ads_sums import (META_COLS, SHEET_NAME, WEBSITE_SHEET_NAME, _get_service,  # noqa: E402
                                 col_for_date, col_letter)

SHEET_ID = os.getenv("ADS_SHEET_ID", "1vM6SIydglC0K0b-bZE5woq--2CK-BubXL8yfdnJqweQ")
ACCOUNT = "act_903156589086283"  # Skin One new
MSG_GOALS = {"REPLIES", "CONVERSATIONS"}
WINDOWS = (7, 30)
THRESH = {"ig": (1.6, 1.0), "site": (1.2, 0.8)}  # (🟢 від, 🟡 від) — окупність за маржею
RNP_ID = "1U-JZBWFBb-zFMpBGF-h50lFgUKtRnN5zyLkuQofiKyI"
RNP_MONTHS = ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень", "Серпень",
              "Вересень", "Жовтень", "Листопад", "Грудень"]
CHANNELS = {"ig": ("Інстаграм", "ФБ"), "site": ("Сайт ФБ", "Сайт Гугл", "Сайт прямі")}
DEFAULT_MARGIN = 0.55
MIN_SPEND = 500  # ₴ за вікно сигналу; менше — «мало даних»
MAIN_DIR = os.path.expanduser("~/Documents/ШІ/morning_tools/ads_main")
OLD_TAB = "Дохід на заявку"

norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()
ID_RE = re.compile(r"\b(1202\d{14})\b")


def meta_ads(since: date, until: date) -> list:
    tok = os.environ["FB_ACCESS_TOKEN"]
    p = {"access_token": tok, "level": "ad", "limit": 500,
         "fields": "ad_id,ad_name,adset_id,campaign_id,spend,optimization_goal",
         "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()})}
    url = f"https://graph.facebook.com/v25.0/{ACCOUNT}/insights?" + urllib.parse.urlencode(p)
    out = []
    while url:
        r = json.load(urllib.request.urlopen(url, timeout=120))
        out += r.get("data", [])
        url = r.get("paging", {}).get("next")
    return out


def meta_active_ids() -> set:
    """ID оголошень, груп і кампаній, де є хоч одне ACTIVE оголошення (для «Статус»)."""
    tok = os.environ["FB_ACCESS_TOKEN"]
    p = {"access_token": tok, "limit": 500, "fields": "id,adset_id,campaign_id,effective_status",
         "filtering": json.dumps([{"field": "effective_status", "operator": "IN", "value": ["ACTIVE"]}])}
    url = f"https://graph.facebook.com/v25.0/{ACCOUNT}/ads?" + urllib.parse.urlencode(p)
    ids = set()
    while url:
        r = json.load(urllib.request.urlopen(url, timeout=120))
        for a in r.get("data", []):
            ids |= {a["id"], a.get("adset_id"), a.get("campaign_id")}
        url = r.get("paging", {}).get("next")
    return ids


def main_csv(w: int, d_end: date):
    """Основний кабінет (без API): {назва: [витрати, активне]} або None, якщо файлу немає."""
    path = os.path.join(MAIN_DIR, f"main_{w}d_{d_end:%d%m}.csv")
    if not os.path.exists(path):
        return None
    out = {}
    for x in csv.DictReader(open(path, encoding="utf-8-sig")):
        nm = x.get("Название объявления") or ""
        if not nm:
            continue
        f = lambda k: float(x.get(k) or 0)
        sp, ch, clk = f("Потраченная сумма (UAH)"), f("Начата переписка"), f("Клики по ссылке")
        if clk > 200 and ch < clk / 20:  # реклама на кліки / відвідування профілю
            continue
        o = out.setdefault(norm(nm), [0.0, False])
        o[0] += sp
        o[1] |= (x.get("Показ рекламы") == "active")
    return out


def google_spend(since: date, until: date) -> float:
    from src.google_ads import client as g
    rows = g.search("SELECT metrics.cost_micros FROM campaign "
                    f"WHERE segments.date BETWEEN '{since.isoformat()}' AND '{until.isoformat()}'")
    return sum(int(r.get("metrics", {}).get("costMicros", 0)) for r in rows) / 1e6


def google_active() -> bool:
    from src.google_ads import client as g
    return bool(g.search("SELECT campaign.id FROM campaign WHERE campaign.status = 'ENABLED'"))


def read_tab(svc, tab: str, d_end: date):
    rng = f"'{tab}'!A1:{col_letter(col_for_date(date(d_end.year, 12, 31)))}3000"
    rows = svc.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=rng,
                                           valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    if not rows or len(rows[0]) < 7 or rows[0][6] != "Всього ₴":
        raise RuntimeError(f"{tab}: очікую «Всього ₴» у G1 (нова розмітка)")
    return rows


def revenue(row: list, d_end: date, days: int) -> float:
    cols = [col_for_date(d_end - timedelta(i)) - 1 for i in range(days) if (d_end - timedelta(i)).year == d_end.year]
    return sum(float(row[c]) for c in cols if c < len(row) and isinstance(row[c], (int, float)))


def _num(x):
    return float(x) if isinstance(x, (int, float)) else 0.0


def rnp_margins(svc, d_end: date) -> dict:
    """{(kind, w): маржинальність} з РНП за останні w днів по d_end. Без даних — DEFAULT_MARGIN."""
    days = {}  # date → {канал або "День": (ТО, маржа)}
    need = {(d_end - timedelta(i)).replace(day=1) for i in range(max(WINDOWS))}
    for m in sorted(need):
        tab = f"РНП День ({RNP_MONTHS[m.month - 1]})"
        try:
            rows = svc.spreadsheets().values().get(spreadsheetId=RNP_ID, range=f"'{tab}'!A38:JZ42",
                                                   valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
        except Exception as e:  # noqa: BLE001
            print(f"[ad_chat_value] РНП {tab}: {e}")
            continue
        if len(rows) < 5:
            continue
        r38, r39, to, mar = rows[0], rows[1], rows[2], rows[4]
        for i, v in enumerate(r38):
            if i == 0 or not isinstance(v, (int, float)) or not 1 <= v <= 31:
                continue
            try:
                d = date(m.year, m.month, int(v))
            except ValueError:
                continue
            cell = lambda row, c: _num(row[c]) if c < len(row) else 0.0
            rec = {"День": (cell(to, i), cell(mar, i))}
            for c in range(max(1, i - 5), i):
                if c < len(r39) and r39[c]:
                    rec[str(r39[c])] = (cell(to, c), cell(mar, c))
            days[d] = rec
    out = {}
    for kind, chans in CHANNELS.items():
        for w in WINDOWS:
            t = mg = 0.0
            for i in range(w):
                rec = days.get(d_end - timedelta(i), {})
                for ch in chans:
                    a, b = rec.get(ch, (0.0, 0.0))
                    t += a
                    mg += b
            if t <= 0:  # немає канальних колонок (старі місяці) — беремо день
                for i in range(w):
                    a, b = days.get(d_end - timedelta(i), {}).get("День", (0.0, 0.0))
                    t += a
                    mg += b
            out[(kind, w)] = mg / t if t > 0 and 0.2 < mg / t < 0.9 else DEFAULT_MARGIN
    return out


def signal(kind, sp7, rv7, sp30, rv30, mp):
    good, bad = THRESH[kind]
    if sp7 >= MIN_SPEND:
        roas, tag = rv7 * mp[(kind, 7)] / sp7, ""
    elif sp30 >= MIN_SPEND:
        roas, tag = rv30 * mp[(kind, 30)] / sp30, " (30 дн.)"
    else:
        return "⚪ мало даних"
    return ("🟢" if roas >= good else "🟡" if roas >= bad else "🔴") + tag


def fmt_roas(rv, sp, margin):
    return round(rv * margin / sp, 2) if sp >= 1 else ""


def build_instagram(rows, d_end, ads, active_ids, mains, mp):
    """{row_index: [Кабінет, Статус, Сигнал, ROAS7, ROAS30]}"""
    new = {w: {} for w in WINDOWS}   # назва → [витрати, ids]
    for w in WINDOWS:
        for x in ads[w]:
            if x.get("optimization_goal") not in MSG_GOALS:
                continue
            o = new[w].setdefault(norm(x["ad_name"]), [0.0, set()])
            o[0] += float(x["spend"])
            o[1].add(x["ad_id"])
    out = {}
    for i, r in enumerate(rows[1:], start=2):
        if not r or not str(r[0]).strip():
            continue
        k = norm(r[0])
        if k in new[30]:
            acct = "Skin One new"
            sp = {w: new[w].get(k, [0.0])[0] for w in WINDOWS}
            status = "активне" if new[30][k][1] & active_ids else "вимкнене"
        elif mains[30] and k in mains[30]:
            acct = "Основний"
            sp = {w: (mains[w] or {}).get(k, [0.0])[0] for w in WINDOWS}
            status = "активне" if mains[30][k][1] else "вимкнене"
        else:
            continue
        rv = {w: revenue(r, d_end, w) for w in WINDOWS}
        out[i] = [acct, status, signal("ig", sp[7], rv[7], sp[30], rv[30], mp),
                  fmt_roas(rv[7], sp[7], mp[("ig", 7)]), fmt_roas(rv[30], sp[30], mp[("ig", 30)])]
    return out


def build_site(rows, d_end, ads, active_ids, g_spend, g_active, mp):
    by_id = {w: {} for w in WINDOWS}
    for w in WINDOWS:
        for x in ads[w]:
            for idk in ("ad_id", "adset_id", "campaign_id"):
                by_id[w][x[idk]] = by_id[w].get(x[idk], 0.0) + float(x["spend"])
    groups = {}  # ключ витрат → [row_index...]
    for i, r in enumerate(rows[1:], start=2):
        if not r or not str(r[0]).strip():
            continue
        lab = str(r[0])
        m = ID_RE.search(lab)
        if "(gclid)" in lab or lab.lower().startswith("google /"):
            groups.setdefault("google", []).append(i)
        elif m and lab.lower().startswith("meta"):
            groups.setdefault(m.group(1), []).append(i)
    out = {}
    for key, idx in groups.items():
        rv = {w: sum(revenue(rows[i - 1], d_end, w) for i in idx) for w in WINDOWS}
        if key == "google":
            sp, acct, status = g_spend, "Google Ads", ("активне" if g_active else "вимкнене")
        else:
            sp = {w: by_id[w].get(key, 0.0) for w in WINDOWS}
            acct, status = "Skin One new", ("активне" if key in active_ids else "вимкнене")
        if sp[30] < 1:
            continue
        line = [acct, status, signal("site", sp[7], rv[7], sp[30], rv[30], mp),
                fmt_roas(rv[7], sp[7], mp[("site", 7)]), fmt_roas(rv[30], sp[30], mp[("site", 30)])]
        for i in idx:
            out[i] = line
    return out


def write(svc, tab, rows, data, note):
    n = len(rows)
    vals = [data.get(i, ["", "", "", "", ""]) for i in range(2, n + 1)]
    svc.spreadsheets().values().batchUpdate(spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": [
        {"range": f"'{tab}'!B1:F1", "values": [META_COLS]},
        {"range": f"'{tab}'!B2:F{n}", "values": vals},
    ]}).execute()
    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID, fields="sheets.properties").execute()
    sid = next(s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == tab)
    svc.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [
        {"updateCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                                   "startColumnIndex": 3, "endColumnIndex": 4},
                         "rows": [{"values": [{"note": note}]}], "fields": "note"}},
    ]}).execute()


def main(d_end: date):
    svc = _get_service()
    ads = {w: meta_ads(d_end - timedelta(w - 1), d_end) for w in WINDOWS}
    active_ids = meta_active_ids()
    mains = {w: main_csv(w, d_end) for w in WINDOWS}
    try:
        g_spend = {w: google_spend(d_end - timedelta(w - 1), d_end) for w in WINDOWS}
        g_act = google_active()
    except Exception as e:  # Google Ads недоступний — сайт без Google
        print(f"[ad_chat_value] Google Ads: {e}")
        g_spend, g_act = {w: 0.0 for w in WINDOWS}, False
    mp = rnp_margins(svc, d_end)
    stamp = f"{datetime.now(ZoneInfo('Europe/Kyiv')):%d.%m %H:%M}"
    pc = lambda k, w: f"{mp[(k, w)] * 100:.1f}%"
    base = (f"Оновлено {stamp}, дані по {d_end:%d.%m}. Окупність = маржа ÷ витрати; маржа = дохід оголошення × "
            f"маржинальність каналу з РНП (Інстаграм+ФБ: {pc('ig', 7)} за 7 дн., {pc('ig', 30)} за 30 дн.; "
            f"сайт: {pc('site', 7)} / {pc('site', 30)}). Беззбитковість = 1,0.\n"
            f"Пороги для окремого оголошення (бачимо ~55–60% продажів реклами): Інстаграм 🟢 ≥1,6 · 🟡 1,0–1,6 · 🔴 <1,0; "
            f"Сайт 🟢 ≥1,2 · 🟡 0,8–1,2 · 🔴 <0,8; ⚪ мало даних (витрат <{MIN_SPEND} ₴ і за 7, і за 30 днів). "
            f"Сигнал за 7 днів; «(30 дн.)» — якщо за 7 днів витрат <{MIN_SPEND} ₴. Акційні оголошення: реальна маржа нижча.")

    ig_rows = read_tab(svc, SHEET_NAME, d_end)
    ig = build_instagram(ig_rows, d_end, ads, active_ids, mains, mp)
    main_note = "основний кабінет — CSV з Ads Manager" if mains[30] else "основний кабінет НЕ враховано (немає CSV за цей день)"
    write(svc, SHEET_NAME, ig_rows, ig, base + f"\nІнстаграм: реклама на переписку; Skin One new — API, {main_note}.")

    site_rows = read_tab(svc, WEBSITE_SHEET_NAME, d_end)
    site = build_site(site_rows, d_end, ads, active_ids, g_spend, g_act, mp)
    write(svc, WEBSITE_SHEET_NAME, site_rows, site,
          base + "\nСайт: витрати Skin One new за ID групи/оголошення з мітки; (gclid) — увесь Google Ads.")

    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID, fields="sheets.properties").execute()
    old = [s["properties"]["sheetId"] for s in meta["sheets"] if s["properties"]["title"] == OLD_TAB]
    if old:
        svc.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [{"deleteSheet": {"sheetId": old[0]}}]}).execute()

    print(f"[ad_chat_value] {d_end}: маржа {pc('ig', 7)}/{pc('ig', 30)} · сайт {pc('site', 7)}/{pc('site', 30)}; "
          f"Інстаграм {len(ig)} рядків, Сайт {len(site)} рядків"
          f"{'' if mains[30] else ' (основний кабінет без CSV)'}")
    return ig_rows, ig, site_rows, site


if __name__ == "__main__":
    d = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(ZoneInfo("Europe/Kyiv")).date() - timedelta(1)
    ig_rows, ig, site_rows, site = main(d)
    for rows, data in ((ig_rows, ig), (site_rows, site)):
        for i, v in sorted(data.items()):
            if v[1] == "активне":
                print(" | ".join(str(x) for x in [str(rows[i - 1][0])[:60]] + v))
