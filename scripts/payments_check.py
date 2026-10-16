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
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta, timezone

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sitniks.client import SitniksClient  # noqa: E402
from src.analyzer.order_status import status_title  # noqa: E402

DEFAULT_DIR = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/Documents/Skin.One/Виписки")
SKIP_STATUSES = {"Відмінено", "Відмовилась"}
TOLERANCE = 2.0  # округлення копійок (1039.5 → 1040)
MAX_DAYS = 2      # платіж шукаємо не далі ніж ±2 дні від дати замовлення

# Українські / російські / латинські варіанти літер → спільний «скелет»
_SKEL = str.maketrans({
    "і": "и", "i": "и", "ї": "и", "ы": "и", "й": "и",
    "є": "е", "э": "е", "ё": "е", "e": "е",
    "a": "а", "o": "о", "c": "с", "p": "р", "x": "х", "k": "к", "m": "м", "t": "т", "h": "н", "b": "в",
    "'": "", "’": "", "`": "", "ʼ": "", "ь": "", "ъ": "",
})


_LAT = [("shch", "щ"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"), ("yu", "ю"), ("ya", "я"),
        ("ye", "є"), ("yi", "ї"), ("a", "а"), ("b", "б"), ("v", "в"), ("h", "г"), ("g", "г"), ("d", "д"), ("e", "е"),
        ("z", "з"), ("y", "и"), ("i", "і"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"),
        ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("f", "ф")]


def translit(s: str) -> str:
    """VALENTYNA KOTSURA → валентина коцура (переказ з картки — ім'я латиницею)."""
    s = s.lower()
    for lat, cyr in _LAT:
        s = s.replace(lat, cyr)
    return s


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
    ps = surname(payer)
    tokens = [skel(t) for t in re.split(r"[\s,.]+", client or "") if len(skel(t)) >= 3]
    # схожість цілих слів, а не лише початку: «Олексюк» ≠ «Олександра», але «Хапайло» ≈ «Харайло»
    if len(ps) >= 3 and any(t == ps or (min(len(t), len(ps)) >= 5 and SequenceMatcher(None, t, ps).ratio() >= 0.8)
                            for t in tokens):
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
        m = re.search(r"Зарахування переказу:\s*([A-Z][A-Z' -]+)$", purpose.strip())
        if m:  # «… Зарахування переказу: VALENTYNA KOTSURA» → «коцура валентина» (прізвище першим)
            parts = translit(m.group(1)).split()
            payer = " ".join(parts[::-1])
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

    near = lambda rec, pay: abs((pay["date"] - rec["day"]).days) <= MAX_DAYS
    close = lambda rec, pay: abs(pay["amount"] - rec["expected"]) <= TOLERANCE and near(rec, pay)
    by_phone = lambda rec, pay: pay["phone"] and pay["phone"] == phone9(rec["phone"]) and close(rec, pay)
    by_name = lambda rec, pay: name_match(rec["client"], pay["payer"], pay["purpose"]) and close(rec, pay)
    name_only = lambda rec, pay: near(rec, pay) and (name_match(rec["client"], pay["payer"], pay["purpose"])
                                                      or (pay["phone"] and pay["phone"] == phone9(rec["phone"])))
    def assign(left, pred, bucket):
        """Усі можливі пари (замовлення, платіж) → спершу найближчі за датою, щоб у клієнтки з кількома
        замовленнями платіж дістався замовленню свого дня, а не сусіднього."""
        pairs = sorted(((abs((p["date"] - r["day"]).days), p["date"] < r["day"], i, j)
                        for i, r in enumerate(left) for j, p in enumerate(payments)
                        if not p["used"] and pred(r, p)))
        done = set()
        for _, _, i, j in pairs:
            if i in done or payments[j]["used"]:
                continue
            payments[j]["used"] = True
            done.add(i)
            res[bucket].append((left[i], payments[j]))
        return [r for i, r in enumerate(left) if i not in done]

    def split(left):
        """Оплата кількома платежами від тієї ж людини (3 155 + 374 = 3 529 за замовлення на 3 528)."""
        rest = []
        for r in left:
            parts = [p for p in payments if not p["used"] and name_only(r, p)]
            if len(parts) >= 2 and abs(sum(p["amount"] for p in parts) - r["expected"]) <= TOLERANCE:
                for p in parts:
                    p["used"] = True
                res["ok"].append((r, parts[0]))
            else:
                rest.append(r)
        return rest

    left = todo
    for pred, bucket in ((by_phone, "ok"), (by_name, "ok")):
        left = assign(left, pred, bucket)
    left = split(left)
    left = assign(left, name_only, "sum_diff")
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
    # Замовлення без передоплати в Sitniks, але від тієї ж людини прийшли гроші на рахунок →
    # ризик подвійної оплати (накладений платіж піде в ТТН). Напр. №17923 Ципій: 1 500 + 2 815,20.
    res["cod_paid"] = []
    for r in res["cod_only"]:
        parts = [p for p in payments if not p["used"] and name_only(r, p)]
        if parts:
            for p in parts:
                p["used"] = True
            res["cod_paid"].append((r, parts))
    res["unknown_payments"] = [p for p in payments if not p["used"]]
    return res


def fmt(x):
    return f"{x:,.2f}".replace(",", " ").replace(".00", "")


def report(d1, d2, res, n_pay):
    ok = res["ok"]
    period = f"{d1:%d.%m}" if d1 == d2 else f"{d1:%d.%m}–{d2:%d.%m.%Y}"
    late = [(r, p) for r, p in ok if p["date"] != r["day"]]
    print(f"Звірка оплат за {period}: платежів у виписках {n_pay}, замовлень з передоплатою "
          f"{len(ok) + len(res['sum_diff']) + len(res['other_payer']) + len(res['unpaid']) + len(res.get('confirmed', []))}")
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
    for r, ps in res.get("cod_paid", []):
        print(f"\n⚠️ №{r['n']} {r['client']}: у Sitniks без передоплати (накладений {fmt(r['total'])} ₴), "
              f"але надійшло {fmt(sum(p['amount'] for p in ps))} ₴ ({', '.join(p['dt'] for p in ps)}) — виправити, щоб не було подвійної оплати")
    print(f"\n❌ Не знайдено оплату ({len(res['unpaid'])}):")
    for r in sorted(res["unpaid"], key=lambda r: (r["day"], r["n"])):
        print(f"  {r['day']:%d.%m} №{r['n']} {r['client']} {r['phone']} — {fmt(r['expected'])} ₴ (усього {fmt(r['total'])} ₴, {r['status']})")
    if res["unknown_payments"]:
        print(f"\n❓ Платежі без замовлення за цей день ({len(res['unknown_payments'])}) — можливо, за інший день:")
        for p in res["unknown_payments"]:
            print(f"  {fmt(p['amount'])} ₴ — {p['payer']} ({p['acct']}, {p['dt']}) «{p['purpose'][:50]}»")
    if res.get("confirmed"):
        print(f"\n☑️ Підтверджено вручну раніше: {len(res['confirmed'])}")
    print(f"\nℹ️ Без передоплати (лише накладений платіж): {len(res['cod_only'])}; "
          f"пропущено (відмінено/відмова): {len(res['skipped'])}")


def load_payments(folder: str = DEFAULT_DIR):
    seen, payments = set(), []
    for f in sorted(glob.glob(os.path.join(folder, "*.xlsx"))):
        for p in parse_statement(f):
            key = (p["acct"], p["dt"], p["amount"], p["purpose"])
            if key not in seen:  # виписки за періоди, що перетинаються
                seen.add(key)
                payments.append(p)
    return payments


def check(d1: date, d2: date, folder: str = DEFAULT_DIR, confirmed=(), resolved_payments=()):
    """confirmed — № замовлень, які користувач підтвердив вручну (оплата на інший рахунок, квитанція);
    resolved_payments — [{"date": "13.10.2026", "amount": 1915}] — платежі, вже пояснені вручну."""
    payments = load_payments(folder)
    # замовлення за 2 дні до періоду теж зіставляємо (щоб їхні платежі не висіли як «без замовлення»),
    # але у звіті показуємо лише період; платежі — лише з дат d1−1 … d2+1
    orders = asyncio.run(load_orders(d1 - timedelta(days=2), d2))
    payments = [p for p in payments if d1 - timedelta(days=1) <= p["date"] <= d2 + timedelta(days=1)]
    res = match(orders, payments)
    inside = lambda r: d1 <= r["day"] <= d2
    conf = {str(x) for x in confirmed}
    res["confirmed"] = []
    res["cod_paid"] = [(r, ps) for r, ps in res["cod_paid"] if inside(r)]
    for k in ("ok", "sum_diff", "other_payer"):
        keep = []
        for r, p in res[k]:
            if not inside(r):
                continue
            if k != "ok" and str(r["n"]) in conf:
                res["confirmed"].append(r)
            else:
                keep.append((r, p))
        res[k] = keep
    for k in ("unpaid", "cod_only", "skipped"):
        rows = [r for r in res[k] if inside(r)]
        if k == "unpaid":
            res["confirmed"] += [r for r in rows if str(r["n"]) in conf]
            rows = [r for r in rows if str(r["n"]) not in conf]
        res[k] = rows
    res["unknown_payments"] = [p for p in res["unknown_payments"]
                               if not any(p["dt"].startswith(x["date"]) and abs(p["amount"] - x["amount"]) < 0.01
                                          and skel(x.get("payer", "")) in skel(p["payer"] + p["purpose"])
                                          for x in resolved_payments)]
    res["n_payments"] = len(payments)
    return res


def main():
    args = sys.argv[1:]
    d1 = date.fromisoformat(args.pop(0)) if args else date.today() - timedelta(days=1)
    d2 = date.fromisoformat(args.pop(0)) if args and re.match(r"\d{4}-\d\d-\d\d$", args[0]) else d1
    folder = args[0] if args else DEFAULT_DIR
    res = check(d1, d2, folder)
    report(d1, d2, res, res["n_payments"])


if __name__ == "__main__":
    main()
