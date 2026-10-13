"""
Звірка передоплат: замовлення Sitniks за день ↔ вхідні платежі у виписках ПриватБанку (xlsx).

Очікувана сума по замовленню = payment.amount (передоплата на рахунок ФОП: 200 ₴ або повна сума).
Замовлення без передоплати (payment.amount порожній / 0) — лише накладений платіж, у банку їх не шукаємо.

Зіставлення (по черзі, кожен платіж — до одного замовлення):
  1. телефон з призначення платежу = телефон клієнта, сума ±2 ₴;
  2. прізвище платника ≈ прізвище клієнта, сума ±2 ₴;
  3. прізвище збігається, але сума інша → «сума не збігається»;
  4. сума збігається з єдиним вільним платежем (платник інший) → «ймовірно, платив хтось інший».

Використання:
  python scripts/payments_check.py 2026-10-12 [2026-10-12] [папка_з_виписками]
Діапазон дат: замовлення всіх днів звіряються з усіма платежами з папки
(оплата могла прийти за день до / після замовлення — береться найближчий за датою платіж).
За замовчуванням папка = iCloud Drive/Documents/Skin.One/Виписки (усі *.xlsx).
"""
import asyncio
import glob
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sitniks.client import SitniksClient  # noqa: E402
from src.analyzer.order_status import status_title  # noqa: E402

DEFAULT_DIR = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Skin.One/Виписки")
SKIP_STATUSES = {"Відмінено", "Відмовилась"}
TOLERANCE = 2.0  # округлення копійок (1039.5 → 1040)

# Українські / російські / латинські варіанти літер → спільний «скелет»
_SKEL = str.maketrans({
    "і": "и", "i": "и", "ї": "и", "ы": "и", "й": "и",
    "є": "е", "э": "е", "ё": "е", "e": "е",
    "a": "а", "o": "о", "c": "с", "p": "р", "x": "х", "k": "к", "m": "м", "t": "т", "h": "н", "b": "в",
    "'": "", "’": "", "`": "", "ʼ": "", "ь": "", "ъ": "",
})


def skel(s: str) -> str:
    s = (s or "").lower().translate(_SKEL)
    s = s.replace("ая", "а").replace("ска", "ска")  # Кухаревская ≈ Кухаревська
    return re.sub(r"[^а-я]", "", s)


def surname(full: str) -> str:
    parts = [p for p in re.split(r"[\s,.]+", full or "") if len(p) > 1]
    return skel(parts[0]) if parts else ""


def name_match(client: str, payer: str, purpose: str = "") -> bool:
    """Прізвище платника (перше слово у виписці) ≈ будь-якому слову з ПІБ клієнта (у Sitniks порядок довільний).
    Запасний варіант: прізвище клієнта (≥5 літер) трапляється в призначенні платежу («крем_чепак маряна»)."""
    payer = re.sub(r"^(ФОП|ТОВ)\s+", "", (payer or "").strip(), flags=re.I)
    ps = surname(payer)[:5]
    tokens = [skel(t) for t in re.split(r"[\s,.]+", client or "") if len(skel(t)) >= 3]
    if len(ps) >= 3 and any(t[:5] == ps for t in tokens):
        return True
    if not purpose or payer != purpose:  # запасний варіант лише коли ПІБ платника не вдалося виділити
        return False
    sp = skel(purpose)
    return any(len(t) >= 5 and t in sp for t in tokens[:2])


def phone9(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[-9:] if len(d) >= 9 else ""


def parse_statement(path: str):
    ws = openpyxl.load_workbook(path, read_only=True, data_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    owner = next((str(r[0]) for r in rows[:10] if r[0] and str(r[0]).startswith("Клієнт")), "")
    owner = re.sub(r"^Клієнт\s+", "", owner).split(" ФОП")[0].title()
    out = []
    for r in rows:
        if not r or not r[1] or not re.match(r"\d\d\.\d\d\.\d{4}$", str(r[1])):
            continue
        amount = float(r[3])
        if amount <= 0:
            continue
        purpose, counterparty = str(r[5] or ""), str(r[7] or "")
        payer = counterparty
        if "Транз.рахунок" in counterparty or counterparty.startswith("ТОВ"):
            m = re.search(r"вiд ([^,]+)", purpose) or re.search(r",\s*([^,]+)$", purpose)
            payer = m.group(1).strip() if m else purpose
        m = re.search(r"(\+?\d[\d\s]{8,})", purpose)
        out.append({
            "acct": owner, "dt": f"{r[1]} {str(r[2])[:5]}", "amount": amount,
            "date": datetime.strptime(str(r[1]), "%d.%m.%Y").date(),
            "payer": payer, "purpose": purpose, "phone": phone9(m.group(1)) if m else "",
            "used": False,
        })
    return out


async def load_orders(d1: date, d2: date):
    a = datetime(d1.year, d1.month, d1.day, tzinfo=timezone(timedelta(hours=3))).astimezone(timezone.utc)
    b = datetime(d2.year, d2.month, d2.day, tzinfo=timezone(timedelta(hours=3))).astimezone(timezone.utc) + timedelta(days=1)
    return await SitniksClient().get_orders_exact(a, b)


def kyiv_day(iso: str) -> date:
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(hours=3)).date()


def match(orders, payments):
    res = {"ok": [], "sum_diff": [], "other_payer": [], "unpaid": [], "cod_only": [], "skipped": []}
    todo = []
    for o in orders:
        st = status_title(o)
        p = (o.get("payment") or {}).get("amount")
        c = o.get("client") or {}
        rec = {"n": o.get("orderNumber") or o["id"], "status": st, "day": kyiv_day(o["createdAt"]), "client": (c.get("fullname") or "").strip(" ,"),
               "phone": c.get("phone") or "", "total": o.get("totalPriceDiscount"), "expected": float(p or 0)}
        if st in SKIP_STATUSES:
            res["skipped"].append(rec)
        elif not p:
            res["cod_only"].append(rec)
        else:
            todo.append(rec)

    def take(rec, pred, bucket):
        cands = [p for p in payments if not p["used"] and pred(rec, p)]
        # найближчий за датою; при рівності — платіж того ж дня або пізніше
        for pay in sorted(cands, key=lambda p: (abs((p["date"] - rec["day"]).days), p["date"] < rec["day"]))[:1]:
                pay["used"] = True
                res[bucket].append((rec, pay))
                return True
        return False

    close = lambda rec, pay: abs(pay["amount"] - rec["expected"]) <= TOLERANCE
    by_phone = lambda rec, pay: pay["phone"] and pay["phone"] == phone9(rec["phone"]) and close(rec, pay)
    by_name = lambda rec, pay: name_match(rec["client"], pay["payer"], pay["purpose"]) and close(rec, pay)
    name_only = lambda rec, pay: name_match(rec["client"], pay["payer"], pay["purpose"]) or (pay["phone"] and pay["phone"] == phone9(rec["phone"]))
    left = todo
    for pred, bucket in ((by_phone, "ok"), (by_name, "ok"), (name_only, "sum_diff")):
        left = [r for r in left if not take(r, pred, bucket)]
    # однакова сума, інший платник — лише якщо такий вільний платіж єдиний
    still = []
    for rec in left:
        cands = [p for p in payments if not p["used"] and close(rec, p) and abs((p["date"] - rec["day"]).days) <= 1]
        if rec["expected"] > 200 and len(cands) == 1:
            cands[0]["used"] = True
            res["other_payer"].append((rec, cands[0]))
        else:
            still.append(rec)
    res["unpaid"] = still
    res["unknown_payments"] = [p for p in payments if not p["used"]]
    return res


def fmt(x):
    return f"{x:,.2f}".replace(",", " ").replace(".00", "")


def report(d1, d2, res, n_pay):
    ok = res["ok"]
    period = f"{d1:%d.%m}" if d1 == d2 else f"{d1:%d.%m}–{d2:%d.%m.%Y}"
    late = [(r, p) for r, p in ok if p["date"] != r["day"]]
    print(f"Звірка оплат за {period}: платежів у виписках {n_pay}, замовлень з передоплатою "
          f"{len(ok) + len(res['sum_diff']) + len(res['other_payer']) + len(res['unpaid'])}")
    print(f"✅ Оплачено (збіг ПІБ/телефону і суми): {len(ok)}"
          + (f", з них {len(late)} оплатою з іншого дня" if late else ""))
    if res["other_payer"]:
        print(f"\n🟡 Сума збігається, платник інший ({len(res['other_payer'])}) — перевірте:")
        for r, p in res["other_payer"]:
            print(f"  №{r['n']} {r['client']} {fmt(r['expected'])} ₴ ← {p['payer']} ({p['acct']}, {p['dt']})")
    if res["sum_diff"]:
        print(f"\n🟠 Платник той самий, сума інша ({len(res['sum_diff'])}):")
        for r, p in res["sum_diff"]:
            print(f"  №{r['n']} {r['client']}: очікувалось {fmt(r['expected'])} ₴, надійшло {fmt(p['amount'])} ₴ ({p['acct']}, {p['dt']})")
    print(f"\n❌ Не знайдено оплату ({len(res['unpaid'])}):")
    for r in sorted(res["unpaid"], key=lambda r: (r["day"], r["n"])):
        print(f"  {r['day']:%d.%m} №{r['n']} {r['client']} {r['phone']} — {fmt(r['expected'])} ₴ (усього {fmt(r['total'])} ₴, {r['status']})")
    if res["unknown_payments"]:
        print(f"\n❓ Платежі без замовлення за цей день ({len(res['unknown_payments'])}) — можливо, за інший день:")
        for p in res["unknown_payments"]:
            print(f"  {fmt(p['amount'])} ₴ — {p['payer']} ({p['acct']}, {p['dt']}) «{p['purpose'][:50]}»")
    print(f"\nℹ️ Без передоплати (лише накладений платіж): {len(res['cod_only'])}; "
          f"пропущено (відмінено/відмова): {len(res['skipped'])}")


def main():
    args = sys.argv[1:]
    d1 = date.fromisoformat(args.pop(0)) if args else date.today() - timedelta(days=1)
    d2 = date.fromisoformat(args.pop(0)) if args and re.match(r"\d{4}-\d\d-\d\d$", args[0]) else d1
    folder = args[0] if args else DEFAULT_DIR
    seen, payments = set(), []
    for f in sorted(glob.glob(os.path.join(folder, "*.xlsx"))):
        for p in parse_statement(f):
            key = (p["acct"], p["dt"], p["amount"], p["purpose"])
            if key not in seen:  # виписки за періоди, що перетинаються
                seen.add(key)
                payments.append(p)
    orders = asyncio.run(load_orders(d1, d2))
    report(d1, d2, match(orders, payments), len(payments))


if __name__ == "__main__":
    main()
