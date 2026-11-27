"""Автодотиск «спитала ціну й замовкла» (Instagram skin.one.ua) — A/B-тест.

Погоджено з власником 27.11.2026:
- кандидат = новий IG-чат, клієнтка спитала ціну, менеджерка надіслала опис/ціни,
  далі тиша, замовлення немає, немає відмови, і чат не в інших дотисках (−10% / реквізити);
- половина кандидатів (група A) отримує ОДНЕ повідомлення, група B — контроль (нічого);
- одне повідомлення на чат назавжди; лише 10:00–20:00 Київ; лише в межах 22 год від
  останнього повідомлення клієнтки (24-годинне вікно Instagram);
- текст затверджений власником (див. TEXT_*).

Режими (env FOLLOWUP_MODE): off | shadow (за замовчуванням: нічого не надсилає, лише
журнал + звіт власнику в Telegram) | live (надсилає групі A).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pytz

KYIV = pytz.timezone("Europe/Kiev")
IG_OWNER = "skin.one.ua"

MIN_SILENCE_H = 3      # чекаємо щонайменше 3 год після останньої відповіді менеджерки
MAX_SINCE_CLIENT_H = 22  # і не пізніше 22 год від останнього повідомлення клієнтки
MAX_CLIENT_MSGS = 4    # довгі консультації — не «лише ціна»
SEND_HOURS = (10, 20)  # [з, до) за Києвом
MAX_SENDS_PER_RUN = 40

TEXT_NAMED = "Добрий день! 🌿 {day} ви цікавились {product}. Хочете, підкажу, чи підійде цей засіб саме вам?"
TEXT_GENERIC = "Добрий день! 🌿 {day} ви цікавились нашим доглядом. Хочете, підкажу, чи підійде він саме вам?"

PRICE_Q = re.compile(r"ц[іiи]н|скільки|скiльки|вартіст|вартує|прайс|почому|сколько|стоимост|price", re.I)
PRICE_A = re.compile(r"\d[\d\s.,]*\s*(грн|₴|uah|гривень)", re.I)
OTHER_FLOW = re.compile(r"знижк\w*\s+10\s*%|10\s*%\s*знижк|−\s*10\s*%|-\s*10\s*%|реквізит|iban|\bUA\d{10,}|оплат|передоплат|privat24|переказ|карт[ауи] для", re.I)
REFUSAL = re.compile(
    r"^\s*(ні|нi|нет)\b|не\s+треба|не\s+потрібно|не\s+цікав|подума|дорого|пізніше|після\s+зарплат|не\s+зараз|не\s+на\s+часі",
    re.I,
)
AGREED = re.compile(r"^\s*так\b|бажаю|хочу\s+замов|замовля|оформ|беру\b|давайте", re.I)


def mode() -> str:
    m = (os.getenv("FOLLOWUP_MODE") or "shadow").strip().lower()
    return m if m in ("off", "shadow", "live") else "shadow"


def group_of(chat_id: str) -> str:
    """Стабільний випадковий поділ: A — надсилаємо, B — контроль."""
    return "A" if int(hashlib.sha1(chat_id.encode()).hexdigest(), 16) % 2 == 0 else "B"


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _is_manager(m: dict) -> bool:
    return bool(m.get("managerName"))


@dataclass
class Verdict:
    ok: bool
    reason: str
    client_last: Optional[datetime] = None
    manager_last: Optional[datetime] = None
    manager_texts: list = field(default_factory=list)


def classify(msgs: list, has_order: bool, now: datetime) -> Verdict:
    """Чи підходить чат для дотиску саме зараз. msgs — повідомлення чату (будь-який порядок)."""
    msgs = sorted((m for m in msgs if (m.get("messageScope") or "standard") == "standard"),
                  key=lambda m: m.get("createdAt") or "")
    if has_order:
        return Verdict(False, "має замовлення")
    cl = [m for m in msgs if not _is_manager(m)]
    mg = [m for m in msgs if _is_manager(m)]
    if not mg:
        return Verdict(False, "менеджерка не відповідала")
    if not cl:
        return Verdict(False, "клієнтка нічого не писала")
    if not _is_manager(msgs[-1]):
        return Verdict(False, "останнє повідомлення від клієнтки")
    if len(cl) > MAX_CLIENT_MSGS:
        return Verdict(False, "довга переписка (консультація)")
    ctexts = [(m.get("text") or "") for m in cl]
    mtexts = [(m.get("text") or "") for m in mg]
    if not any(PRICE_Q.search(t) for t in ctexts):
        return Verdict(False, "не питала ціну")
    if not (any(PRICE_A.search(t) for t in mtexts) or any(m.get("attachments") for m in mg)):
        return Verdict(False, "ціну не надіслали")
    if any(OTHER_FLOW.search(t) for t in mtexts):
        return Verdict(False, "інший дотиск (−10% / реквізити)")
    if any(REFUSAL.search(t) for t in ctexts):
        return Verdict(False, "відмова / «подумаю»")
    if any(AGREED.search(t) for t in ctexts):
        return Verdict(False, "погодилась — веде менеджерка")
    client_last = _ts(cl[-1]["createdAt"])
    manager_last = _ts(mg[-1]["createdAt"])
    v = Verdict(False, "", client_last, manager_last, mtexts)
    if now - manager_last < timedelta(hours=MIN_SILENCE_H):
        v.reason = "ще рано (<3 год тиші)"
        return v
    if now - client_last > timedelta(hours=MAX_SINCE_CLIENT_H):
        v.reason = "вікно 22 год минуло"
        return v
    v.ok, v.reason = True, "кандидат"
    return v


def day_word(client_last: datetime, now: datetime) -> str:
    return "Сьогодні" if client_last.astimezone(KYIV).date() == now.astimezone(KYIV).date() else "Вчора"


def render(product: Optional[str], client_last: datetime, now: datetime) -> str:
    day = day_word(client_last, now)
    if product:
        return TEXT_NAMED.format(day=day, product=product)
    return TEXT_GENERIC.format(day=day)


# ---------- назва засобу (орудний відмінок) ----------

_PRODUCT_PROMPT = (
    "Нижче повідомлення менеджерки магазину косметики клієнтці в Instagram. "
    "Визнач ОДИН засіб, про ціну якого йдеться. Поверни тільки JSON "
    '{"product": "<коротка назва в орудному відмінку, щоб читалось «ви цікавились …», '
    'напр. «кремом з вітаміном К USOLAB» або «сироваткою Azulene Cica»>"} '
    'або {"product": null}, якщо засобів кілька чи назва незрозуміла. Не вигадуй.'
)


async def extract_product(manager_texts: list) -> Optional[str]:
    """Назва засобу через Claude; будь-яка помилка → None (тоді загальний текст)."""
    from src.config import settings
    if not settings.ANTHROPIC_API_KEY:
        return None
    text = "\n---\n".join(t for t in manager_texts if t.strip())[:6000]
    if not text:
        return None
    try:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = await client.messages.create(
            model="claude-opus-5-5",
            max_tokens=1024,
            output_config={"effort": "low"},
            system=_PRODUCT_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        if resp.stop_reason == "refusal":
            return None
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        m = re.search(r"\{.*\}", raw, re.S)
        name = (json.loads(m.group(0)).get("product") if m else None) or None
        if name and 2 <= len(name) <= 60 and "\n" not in name:
            name = re.sub(r"\s*\(.*?\)", "", name)
            return name.strip().strip("«»\"' ") or None
    except Exception as e:  # noqa: BLE001 — дотиск не має падати через назву
        print(f"[followup] product extraction failed: {e}")
    return None


# ---------- журнал (Supabase analytics, таблиця followup_log) ----------

def _db():
    from src.database.supabase_client import get_client
    return get_client()


def logged_chat_ids(chat_ids: list) -> set:
    if not chat_ids:
        return set()
    res = _db().table("followup_log").select("chat_id").in_("chat_id", chat_ids).execute()
    return {r["chat_id"] for r in (res.data or [])}


def log_row(row: dict):
    _db().table("followup_log").upsert(row, on_conflict="chat_id").execute()


# ---------- запуск ----------

async def run(now: Optional[datetime] = None, notify: bool = True, dry: bool = False) -> dict:
    """Один прохід: знайти кандидатів, записати в журнал, (live) надіслати групі A, звіт власнику.
    dry=True — лише показати кандидатів: без годин роботи, журналу, відправки і звіту."""
    from src.sitniks.client import SitniksClient

    m = mode()
    now = now or datetime.now(pytz.utc)
    if m == "off":
        return {"mode": m, "skipped": "off"}
    h = now.astimezone(KYIV).hour
    if not dry and not (SEND_HOURS[0] <= h < SEND_HOURS[1]):
        return {"mode": m, "skipped": f"поза годинами ({h}:00)"}

    sc = SitniksClient()
    stats: dict = {"mode": m, "checked": 0, "reasons": {}, "A": [], "B": [], "errors": []}
    try:
        chats = await sc.get_all_chats(now - timedelta(hours=48), now, by_first_message=True)
        chats = [c for c in chats if c.get("ownerName") == IG_OWNER and c.get("initialSource") == "instagram"]
        # дешевий префільтр за часом останнього повідомлення чату
        chats = [c for c in chats if c.get("lastMessageCreatedAt")
                 and timedelta(hours=MIN_SILENCE_H) <= now - _ts(c["lastMessageCreatedAt"]) <= timedelta(hours=MAX_SINCE_CLIENT_H + 2)]
        done = logged_chat_ids([c["id"] for c in chats])
        chats = [c for c in chats if c["id"] not in done]
        with_order: set = set()
        if chats:
            orders = await sc.get_orders(now - timedelta(days=3), now + timedelta(days=1))
            with_order = {o.get("chatId") for o in orders if o.get("chatId")}
        sent = 0
        for c in chats:
            stats["checked"] += 1
            msgs = await sc.get_chat_messages(c["id"])
            v = classify(msgs, c["id"] in with_order, now)
            stats["reasons"][v.reason] = stats["reasons"].get(v.reason, 0) + 1
            if not v.ok:
                continue
            g = group_of(c["id"])
            product = await extract_product(v.manager_texts) if g == "A" else None
            text = render(product, v.client_last, now) if g == "A" else ""
            row = {
                "chat_id": c["id"], "mode": m, "grp": g,
                "manager": c.get("assignedManagerName"), "client_name": c.get("userName"),
                "user_id": c.get("userId"), "product": product, "message": text or None,
                "client_last_at": v.client_last.isoformat(), "manager_last_at": v.manager_last.isoformat(),
                "found_at": now.isoformat(), "sent_at": None, "sent_ok": None, "error": None,
            }
            if not dry and m == "live" and g == "A" and sent < MAX_SENDS_PER_RUN:
                try:
                    await sc.send_message(c["id"], text)
                    row.update(sent_at=datetime.now(pytz.utc).isoformat(), sent_ok=True)
                    sent += 1
                except Exception as e:  # noqa: BLE001
                    row.update(sent_ok=False, error=str(e)[:300])
                    stats["errors"].append(f"{c['id']}: {e}")
            if not dry:
                log_row(row)
            stats[g].append(row)
    finally:
        await sc.close()

    if notify and not dry and (stats["A"] or stats["B"] or stats["errors"]):
        await _notify(stats, now)
    return stats


def report_text(stats: dict, now: datetime) -> str:
    t = now.astimezone(KYIV).strftime("%d.%m %H:%M")
    live = stats["mode"] == "live"
    head = "🟢 Автодотиск" if live else "👻 Автодотиск (тіньовий режим — нічого НЕ надіслано)"
    lines = [f"{head} · {t}",
             f"Перевірено чатів: {stats['checked']} · група A: {len(stats['A'])} · контроль B: {len(stats['B'])}"]
    for r in stats["A"]:
        verb = "надіслано" if r.get("sent_ok") else ("помилка" if r.get("sent_ok") is False else "надіслав би")
        lines.append(f"\n• {r['client_name'] or '—'} (менеджерка {r['manager'] or '—'}) — {verb}:\n  «{r['message']}»")
    if stats["B"]:
        lines.append("\nКонтроль (нічого не пишемо): " + ", ".join((r["client_name"] or "—") for r in stats["B"]))
    if stats["errors"]:
        lines.append("\n⚠️ Помилки: " + "; ".join(stats["errors"][:5]))
    return "\n".join(lines)[:3900]


async def _notify(stats: dict, now: datetime):
    try:
        from src.config import settings
        from src.telegram_bot.bot import bot
        chat = settings.TELEGRAM_SHADOW_CHAT_ID or settings.TELEGRAM_LEADERSHIP_CHAT_ID
        if chat:
            await bot.send_message(chat, report_text(stats, now))
    except Exception as e:  # noqa: BLE001
        print(f"[followup] notify failed: {e}")


async def followup_job():
    try:
        res = await run()
        print(f"[followup] {res.get('mode')} checked={res.get('checked')} A={len(res.get('A', []))} "
              f"B={len(res.get('B', []))} {res.get('skipped', '')} reasons={res.get('reasons')}")
    except Exception as e:  # noqa: BLE001
        print(f"[followup] FAILED: {e}")
