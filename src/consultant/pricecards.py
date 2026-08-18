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


# Загальні слова-категорії — самі по собі НЕ визначають конкретний товар (за 4-літерною основою).
# Напр. «кремчик»/«крем»/«крему» → основа «крем» → не даємо впевненого збігу, краще перепитати.
_GENERIC_STEMS = {
    "крем", "гель", "тоне", "сиро", "засі", "засо", "маск", "пудр", "флюї",
    "олій", "догл", "прод", "това", "баль", "моло", "міце", "емул",
}


def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"\w+", (s or "").lower()) if len(t) > 3]


def _is_generic(word: str) -> bool:
    return word[:4] in _GENERIC_STEMS


def _stem_match(a: str, b: str) -> bool:
    """Стійке до українських відмінків порівняння: «вітамін» ~ «вітаміном» (спільна основа)."""
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4:
        return a.startswith(b[:4]) or b.startswith(a[:4])
    return False


def _overlap(query: list[str], target: list[str]) -> int:
    """Скільки унікальних слів запиту мають збіг (за основою) у цільовому наборі."""
    cnt = 0
    for q in set(query):
        if any(_stem_match(q, t) for t in target):
            cnt += 1
    return cnt


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
            score = _overlap(qa, _tokens(key))
            if score > best_score:
                best, best_score = body, score
        if best_score >= 2:
            return best

    # 2) збіг за текстом клієнтки (назвала товар) — стійко до відмінків
    if text:
        qt = _tokens(text)
        best, best_matched = "", []
        for key, body in cards:
            tgt = _tokens(key) + _tokens(body[:200])
            matched = [q for q in set(qt) if any(_stem_match(q, t) for t in tgt)]
            if len(matched) > len(best_matched):
                best, best_matched = body, matched
        # Впевнений збіг: 2 будь-яких слова АБО 1 довге ХАРАКТЕРНЕ (не загальне «крем/гель»)
        strong = [m for m in best_matched if len(m) >= 6 and not _is_generic(m)]
        if len(best_matched) >= 2 or strong:
            return best

    return ""
