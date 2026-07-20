"""Будує бібліотеку КАРТОК ТОВАРІВ з реальних відповідей дівчат на запит ціни.

Клієнтка з реклами пише «Ціна?» → менеджер відповідає карткою: назва + опис + склад +
ціни по об'ємах (розпив/оригінал). Ці відповіді — готові шаблони. Скрипт збирає канонічну
(найповнішу) картку по кожному товару/рекламі й пише clients/skin_one.price_cards.md.

Запуск:
    source venv/bin/activate
    PYTHONPATH=. python scripts/mine_price_cards.py [days] [max_chats]
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from src.sitniks.client import SitniksClient

_ROOT = Path(__file__).resolve().parents[1]

PRICE_RE = re.compile(
    r"(ці́?н[аиуо]|вартіст|вартост|по\s?чому|почому|скільки\s+кошт|коштує|"
    r"цен[аыу]|стоимост|прайс|price)",
    re.IGNORECASE,
)
# У справжній картці — кілька рядків «об'єм - ціна»
VOL_PRICE_RE = re.compile(r"\d+\s*мл\s*[-–—]\s*\d+", re.IGNORECASE)
GREETING_RE = re.compile(r"^.*на зв.?язку.*$", re.IGNORECASE | re.MULTILINE)

# Токени, що вказують на рядок-назву товару (для витягування ключа)
_PRODUCT_TOKENS = (
    "крем", "тонер", "гель", "сироват", "маска", "пудр", "спф", "spf", "cream",
    "usolab", "smart4derma", "ag skin", "bio ", "флюїд", "олія", "пілінг", "ретинол",
    "вітамін", "емульс", "міцеляр", "молочко", "бальзам", "шампун",
)


def _product_key(body: str, ad: str) -> str:
    """Ключ картки: заголовок реклами або рядок-назва товару (не розмовний уривок)."""
    if ad:
        return ad.strip()
    for ln in body.splitlines():
        s = ln.strip(" 🧴✨🔥🟢☀️▪️✅•✔️️⬇➡️🌟")
        if not (8 <= len(s) <= 70) or s.endswith("?"):
            continue
        low = s.lower()
        upper_ratio = sum(1 for ch in s if ch.isupper()) / max(len(s), 1)
        if upper_ratio > 0.4 or any(t in low for t in _PRODUCT_TOKENS):
            return s
    return ""


def _is_client(m: dict) -> bool:
    return not (m.get("managerName") or "").strip()


def _text(m: dict) -> str:
    return (m.get("text") or "").strip()


def _strip_greeting(reply: str) -> str:
    """Прибрати рядок-привітання (персона додається агентом окремо)."""
    return GREETING_RE.sub("", reply).strip()


def _first_price_card(messages: list[dict]) -> tuple[str, str] | None:
    """(ad_or_product_key, manager_card) для першого запиту ціни в чаті."""
    for i, m in enumerate(messages):
        if not _is_client(m) or not PRICE_RE.search(_text(m)):
            continue
        parts: list[str] = []
        for nxt in messages[i + 1:]:
            if _is_client(nxt):
                break
            if _text(nxt):
                parts.append(_text(nxt))
        reply = "\n".join(parts)
        # справжня картка = ≥2 рядки «об'єм - ціна» (розпив + оригінал тощо)
        if len(VOL_PRICE_RE.findall(reply)) < 2:
            continue
        ad = (m.get("adInfo") or {}).get("adTitle") or ""
        body = _strip_greeting(reply)
        key = _product_key(body, ad)
        if not key:
            continue
        return key.strip(), body
    return None


async def main() -> None:
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    max_chats = int(sys.argv[2]) if len(sys.argv) > 2 else 400

    client = SitniksClient()
    now = datetime.now()
    chats = await client.get_all_chats(now - timedelta(days=days), now)
    print(f"Чатів за {days} днів: {len(chats)} · скануємо до {max_chats}", flush=True)

    # по кожному ключу лишаємо найповнішу (найдовшу) картку
    cards: dict[str, str] = {}
    scanned = 0
    for c in chats[:max_chats]:
        scanned += 1
        try:
            msgs = await client.get_chat_messages(c["id"])
        except Exception:
            continue
        found = _first_price_card(msgs)
        if not found:
            continue
        key, body = found
        if key and (key not in cards or len(body) > len(cards[key])):
            cards[key] = body
        if scanned % 50 == 0:
            print(f"  ...проскановано {scanned}, карток {len(cards)}", flush=True)
    await client.close()

    print(f"Проскановано: {scanned} · унікальних карток: {len(cards)}", flush=True)

    # Пишемо бібліотеку, відсортовану за повнотою картки
    out = [
        "# Картки товарів skin.one (відповіді на запит ціни)",
        "> Зібрано з реальних відповідей консультантів на «Ціна?» з реклами. "
        "Формат-шаблон: назва + короткий опис/склад + ціни по об'ємах (розпив/оригінал).",
        "",
    ]
    for key, body in sorted(cards.items(), key=lambda kv: -len(kv[1])):
        out.append(f"## {key}")
        out.append(body)
        out.append("")
    path = _ROOT / "clients" / "skin_one.price_cards.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"✓ {path.relative_to(_ROOT)} ({len(cards)} карток, {path.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    asyncio.run(main())
