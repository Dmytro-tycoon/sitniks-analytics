"""Ранковий збір даних одним запуском — друкує лише ЗМІНИ.

  python scripts/morning.py                 # учора + перевірка 2 попередніх днів, усі блоки
  python scripts/morning.py --date 2026-10-13 --days 3 --only rnp,ads,pay,mgr [--dry]

Блоки:
  rnp — РНП «Рука на пульсі» (scripts/face_channels.py) за D-(days-1)…D;
  ads — «Ефективність реклами 2»: вкладка «Сайт» за D-(days-1)…D, «Інстаграм» за D-1…D;
  pay — звірка передоплат з виписками ПриватБанку (scripts/payments_check.py) за D-(days-1)…D;
  mgr — «Звіт по менеджерам» по каналах (scripts/managers_sheet.py) за D-(days-1)…D, з листопада 2026;
        вкладку нового місяця створює сам.

Ручні рішення користувача — config/morning_overrides.json (винятки каналів, витрати зі скрінів,
підтверджені оплати). Стан попереднього запуску — data/morning_state.json (для звіту змін).
"""
import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path.home() / "Documents" / "sitniks-analytics" / "data"  # постійна папка (скрипт часто запускається з worktree)
os.environ.setdefault("REPEAT_INDEX_PATH", str(DATA / "client_first_purchase.json"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import face_channels as fc  # noqa: E402
import managers_sheet as ms  # noqa: E402
import payments_check as pc  # noqa: E402

OVERRIDES = ROOT / "config" / "morning_overrides.json"
STATE = Path(os.getenv("MORNING_STATE_PATH", DATA / "morning_state.json"))
SHORT = {"Інстаграм": "Інст", "ФБ": "ФБ", "Сайт ФБ": "СайтФБ", "Сайт Гугл": "СайтГугл", "Сайт прямі": "СайтПрямі"}
MGR_START = date(2026, 11, 1)  # з листопада — нова мотивація по каналах (30.10.2026)
SHEETS_PAUSE = 10  # квота Google Sheets: 60 читань/хв на сервісний акаунт


def short_label(k):
    """meta / skinone_catalog_2209 / 120260678712650059 / catalog (fbclid) → meta / catalog"""
    parts = [x.strip() for x in k.split(" (")[0].split("/")]
    return parts[0] if len(parts) == 1 else f"{parts[0]} / {parts[-1]}"


def money(x):
    return f"{x:,.2f}".replace(",", " ").replace(".", ",").replace(",00", "")


def retry(fn, *a, tries=3, **kw):
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as e:  # Sitniks інколи рве з'єднання, Sheets — 429
            if i == tries - 1:
                raise
            print(f"  … повтор після помилки {type(e).__name__}")
            time.sleep(20)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def dash_meta():
    key = os.getenv("DASH_RNP_KEY") or getattr(fc.settings, "DASH_RNP_KEY", "")
    try:
        with urllib.request.urlopen(fc.DASH_URL.format(key=key), timeout=60) as r:
            d = json.load(r)
        return f"Meta {d['meta'].get('updatedAt')}, Google {d['google'].get('updatedAt')}"
    except Exception:
        return "недоступний"


# ─── РНП ────────────────────────────────────────────────────────────────
def rnp_day(day, ov, prev, dry):
    st = retry(lambda: asyncio.run(fc.collect(day, ov.get("rnp_site_channel"))))
    ads = fc.fetch_site_ads(day)
    manual = set(ov.get("rnp_manual_ads", {}).get(day.isoformat(), []))
    if not dry:
        with contextlib.redirect_stdout(io.StringIO()):  # без «→ колонка …»
            retry(fc.write, day, st, ads, skip_ad_channels=manual)
    cur = {ch: {"to": round(st[ch]["to"], 2), "sales": int(st[ch]["sales"]), "leads": int(st[ch]["leads"]),
                "orders": st["_orders"][ch]} for ch in fc.CHANNELS}
    tot_to = sum(c["to"] for c in cur.values())
    tot_s = sum(c["sales"] for c in cur.values())
    head = f" {day:%d.%m}:"
    if not prev:
        chans = " · ".join(f"{SHORT[ch]} {money(cur[ch]['to'])}/{cur[ch]['sales']}" for ch in fc.CHANNELS)
        print(f"{head} ТО {money(tot_to)} ₴, продажі {tot_s}, заявки {sum(c['leads'] for c in cur.values())} | {chans}")
    else:
        lines = []
        for ch in fc.CHANNELS:
            a, b = prev.get(ch, {}).get("orders", {}), cur[ch]["orders"]
            ch_lines = [f"+№{n} {money(v)}" for n, v in b.items() if n not in a]
            ch_lines += [f"−№{n} {money(v)}" for n, v in a.items() if n not in b]
            ch_lines += [f"№{n} {money(a[n])}→{money(v)}" for n, v in b.items() if n in a and abs(a[n] - v) > 0.01]
            if ch_lines:
                d = cur[ch]["to"] - prev[ch]["to"]
                lines.append(f"{ch} {'+' if d >= 0 else '−'}{money(abs(d))} ₴ ({', '.join(ch_lines)})")
        p_to = sum(c["to"] for c in prev.values())
        if lines:
            print(f"{head} {'; '.join(lines)} → день {money(tot_to)} ₴ (було {money(p_to)}), продажі {tot_s}")
        else:
            print(f"{head} без змін ({money(tot_to)} ₴)")
    ad_txt = ", ".join(f"{SHORT[ch]} {money(float(v['spend']))} ₴" + (" [вручну, не чіпав]" if ch in manual else "")
                       for ch, v in ads.items())
    if ad_txt:
        print(f"        реклама сайту: {ad_txt}")
    return cur


# ─── Ефективність реклами 2 ─────────────────────────────────────────────
def site_tab_day(day, prev, dry):
    from src.analyzer.site_orders import fetch_site_orders_for_date, group_by_ad_label
    from src.sheets.ads_sums import AdsSumsSheet, WEBSITE_SHEET_NAME
    orders = retry(lambda: asyncio.run(fetch_site_orders_for_date(day)))
    sums, _ = group_by_ad_label(orders)
    sums = {k: round(v, 2) for k, v in sums.items()}
    if not dry:
        sheet_id = os.getenv("ADS_SHEET_ID") or getattr(fc.settings, "ADS_SHEET_ID", "")
        retry(AdsSumsSheet(sheet_id, sheet_name=WEBSITE_SHEET_NAME).write_day, day, sums)
    total = sum(sums.values())
    if prev is None:
        print(f" Сайт {day:%d.%m}: {len(orders)} замовл., {money(total)} ₴ — "
              + "; ".join(f"{short_label(k)} {money(v)}" for k, v in sorted(sums.items(), key=lambda x: -x[1])))
    else:
        diff = [f"{short_label(k)}: {money(prev.get(k, 0))}→{money(sums.get(k, 0))}"
                for k in sorted(set(sums) | set(prev)) if abs(prev.get(k, 0) - sums.get(k, 0)) > 0.01]
        print(f" Сайт {day:%d.%m}: " + ("; ".join(diff) + f" → {money(total)} ₴" if diff else f"без змін ({money(total)} ₴)"))
    return sums


def insta_tab_day(day, prev, dry):
    from src.sheets.ads_sums import write_daily_sums_to_sheet
    if dry:
        print(f" Інстаграм {day:%d.%m}: пропущено (--dry)")
        return prev
    r = retry(lambda: asyncio.run(write_daily_sums_to_sheet(day)))
    total = round(r.get("total_sum", 0), 2)
    if prev is not None and abs(prev - total) <= 0.01:
        print(f" Інстаграм {day:%d.%m}: без змін ({money(total)} ₴)")
    else:
        was = f" (було {money(prev)})" if prev is not None else ""
        print(f" Інстаграм {day:%d.%m}: {money(total)} ₴, міток {r.get('ads_written')}, "
              f"стара атрибуція {money(r.get('stale_added_to_direct') or 0)}{was}")
    return total


# ─── Оплати ──────────────────────────────────────────────────────────────
def payments(d1, d2, ov, prev_state):
    """Повертає новий стан звірки (передоплати, відкриті неоплачені) для data/morning_state.json."""
    res = retry(pc.check, d1, d2, pc.DEFAULT_DIR, ov.get("payments_confirmed", []), ov.get("payments_resolved", []),
                prev_state)
    n = len(res["ok"]) + len(res["sum_diff"]) + len(res["other_payer"]) + len(res["unpaid"]) + len(res["confirmed"])
    print(f" Передоплат {n}: ✅ {len(res['ok'])}, ☑️ підтверджено вручну {len(res['confirmed'])}, "
          f"накладений платіж {len(res['cod_only'])}")
    for r, p in res["other_payer"]:
        print(f"  🟡 №{r['n']} {r['client']} {money(r['expected'])} ← {p['payer']} ({p['dt']})")
    for r, p in res["sum_diff"]:  # noqa
        print(f"  🟠 №{r['n']} {r['client']}: треба {money(r['expected'])}, прийшло {money(p['amount'])} ({p['dt']})")
    for r, ps in res.get("cod_paid", []):
        print(f"  ⚠️ №{r['n']} {r['client']}: у Sitniks без передоплати (накладений {money(r['total'])}), "
              f"а надійшло {money(sum(p['amount'] for p in ps))} ₴ — подвійна оплата?")
    for r, p in res.get("recovered", []):
        print(f"  ✅ раніше без оплати №{r['n']} {r['client']} {money(r['expected'])} ← {p['payer']} ({p['dt']})")
    for r in sorted(res["unpaid"], key=lambda r: (r["day"], r["n"])):
        note = (" — передоплату змінено в Sitniks" if str(r["n"]) in res.get("changed", ())
                else " — з минулих днів" if r.get("ext") else "")
        print(f"  ❌ {r['day']:%d.%m}{note} №{r['n']} {r['client']} {r['phone']} — {money(r['expected'])} ₴ ({r['status']})")
    for p in res["unknown_payments"]:
        print(f"  ❓ {money(p['amount'])} ₴ {p['payer']} ({p['acct'].split()[1] if ' ' in p['acct'] else p['acct']}, {p['dt']})")
    return res["state"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--only", default="rnp,ads,pay,mgr")
    ap.add_argument("--dry", action="store_true", help="нічого не писати в таблиці")
    a = ap.parse_args()
    blocks = set(a.only.split(","))
    days = [a.date - timedelta(days=i) for i in range(a.days - 1, -1, -1)]
    ov = load_json(OVERRIDES, {})
    state = load_json(STATE, {})
    for k in ("rnp", "site", "insta"):
        state.setdefault(k, {})

    if "rnp" in blocks:
        print(f"РНП (дашборд: {dash_meta()})")
        for i, d in enumerate(days):
            if i:
                time.sleep(SHEETS_PAUSE)
            state["rnp"][d.isoformat()] = rnp_day(d, ov, state["rnp"].get(d.isoformat()), a.dry)
    if "ads" in blocks:
        print("Ефективність реклами 2")
        for d in days:
            time.sleep(SHEETS_PAUSE if "rnp" in blocks or d != days[0] else 0)
            state["site"][d.isoformat()] = site_tab_day(d, state["site"].get(d.isoformat()), a.dry)
        # «Інстаграм»: учора + перевірка позавчора (замовлення підтверджують із запізненням)
        for d in [a.date - timedelta(days=i) for i in (1, 0)]:
            time.sleep(SHEETS_PAUSE)
            state["insta"][d.isoformat()] = insta_tab_day(d, state["insta"].get(d.isoformat()), a.dry)
    if "pay" in blocks:
        print(f"Оплати {days[0]:%d.%m}–{days[-1]:%d.%m}")
        state["pay"] = payments(days[0], days[-1], ov, state.get("pay"))
    if "mgr" in blocks:
        mgr_days = [d for d in days if d >= MGR_START]
        if mgr_days:
            print("Звіт по менеджерам")
        for d in mgr_days:
            if not a.dry and not ms.has_channel_tab(d):
                ms.create_month(d.year, d.month)
            data = retry(lambda: asyncio.run(ms.collect(d)))
            ms.show(d, data)
            if not a.dry:
                ms.write(d, data)
    if not a.dry:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
