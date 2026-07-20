"""Пошук релевантної картки товару для відповіді на запит ціни.

Клієнтка питає «Ціна?» (часто з реклами) → знаходимо картку потрібного товару
й даємо агенту, щоб він відповів так само, як дівчата-консультанти.
Джерело — clients/<client>.price_cards.md (генерує scripts/mine_price_cards.py).
"""
from __future__ import annotations

import re

from src.config import settings

# Запит ціни від клієнтки (той самий, що й у майнері)
PRICE_QUESTION_RE = re.compile(
    r"(ці́?н[аиуо]|вартіст|вартост|по\s?чому|почому|скільки\s+кошт|коштує|"
    r"цен[аыу]|стоимост|прайс|price)",
    re.IGNORECASE,
)


def is_price_question(text: str) -> bool:
    return bool(PRICE_QUESTION_RE.search(text or ""))


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"\w+", (s or "").lower()) if len(t) > 3}


def _parse_cards() -> list[tuple[str, str]]:
    """Розбирає price_cards.md на список (ключ, тіло картки)."""
    raw = settings.price_cards
    if not raw:
        return []
    cards: list[tuple[str, str]] = []
    key, body = None, []
    for line in raw.splitlines():
        if line.startswith("## "):
            if key is not None:
                cards.append((key, "\n".join(body).strip()))
            key, body = line[3:].strip(), []
        elif key is not None:
            body.append(line)
    if key is not None:
        cards.append((key, "\n".join(body).strip()))
    return cards


def find_card(ad_title: str | None = None, text: str | None = None) -> str:
    """Найрелевантніша картка: спершу за рекламою (точний ключ), потім за текстом.

    Повертає тіло картки або "" якщо впевненого збігу немає (щоб агент не вгадував ціну).
    """
    cards = _parse_cards()
    if not cards:
        return ""

    # 1) точний/сильний збіг за рекламним заголовком
    if ad_title:
        at = ad_title.strip().lower()
        for key, body in cards:
            if key.lower() == at:
                return body
        qa = _tokens(ad_title)
        best, best_score = "", 0
        for key, body in cards:
            score = len(qa & _tokens(key))
            if score > best_score:
                best, best_score = body, score
        if best_score >= 2:
            return best

    # 2) збіг за текстом клієнтки (назвала товар)
    if text:
        qt = _tokens(text)
        best, best_score = "", 0
        for key, body in cards:
            score = len(qt & (_tokens(key) | _tokens(body[:200])))
            if score > best_score:
                best, best_score = body, score
        if best_score >= 2:
            return best

    return ""
