"""Збірка плейбука для продавця з накопиченого тон-оф-войс кращих менеджерів.

Дані беруться з таблиці tone_of_voice (наповнює scripts/build_playbook.py з good-діалогів).
Якщо БД недоступна — повертаємо порожньо, агент працює на sales_context + каталозі.
"""
from __future__ import annotations


def _norm(s: str) -> str:
    """Ключ для дедуплікації: постійні клієнти дають багато однакових прийомів."""
    return " ".join((s or "").lower().split())[:80]


# Прийоми/фрази етапу підбору-закриття — поза роллю агента-кваліфікатора (це роблять люди).
_CLOSING_MARKERS = (
    "оформ", "оплат", "накладн", "передопла", "предопла", "доставк", "замовлен",
    "картк", "карту", "скрін", "реквізит", "грн", "об'єм", "обʼєм", "объ", "ціна",
    "ціни", "цін ", "прайс", "рахую", "порахую", "суму", "сума", "подарунок",
)


def _is_closing(*texts: str) -> bool:
    blob = " ".join(t or "" for t in texts).lower()
    return any(m in blob for m in _CLOSING_MARKERS)


def get_playbook(
    limit_rows: int = 40, max_moves: int = 24, max_objections: int = 16, qualify_only: bool = True
) -> str:
    """Готовий текстовий плейбук для system-промпта: тон, фрази, прийоми, заперечення.

    qualify_only=True (за замовч.) — лишає лише прийоми кваліфікації, викидає підбір/ціни/оплату,
    бо агент-консультант доводить лише до передачі живому консультанту.
    """
    try:
        from src.database.supabase_client import _db

        rows = _db().table("tone_of_voice").select("*").limit(limit_rows).execute().data
    except Exception:
        return ""
    if not rows:
        return ""

    phrases: list[str] = []
    moves: list[str] = []
    objections: list[str] = []
    seen_phrase: set[str] = set()
    seen_move: set[str] = set()
    seen_obj: set[str] = set()

    for r in rows:
        for ph in ((r.get("voice") or {}).get("signature_phrases") or []):
            if qualify_only and _is_closing(ph):
                continue
            k = _norm(ph)
            if ph and k not in seen_phrase:
                seen_phrase.add(k)
                phrases.append(ph.strip())
        for mv in (r.get("winning_moves") or []):
            if not isinstance(mv, dict):
                continue
            sit, resp = mv.get("situation", ""), mv.get("response", "")
            if qualify_only and _is_closing(sit, resp):
                continue
            k = _norm(resp)
            if resp and k not in seen_move:
                seen_move.add(k)
                moves.append(f"• Коли клієнт: {sit} → {resp}")
        for ob in (r.get("objection_playbook") or []):
            if not isinstance(ob, dict):
                continue
            obj, reply = ob.get("objection", ""), ob.get("best_reply", "")
            if qualify_only and _is_closing(obj, reply):
                continue
            k = _norm(obj)
            if reply and k not in seen_obj:
                seen_obj.add(k)
                objections.append(f"• Заперечення «{obj}» → {reply}")

    parts: list[str] = []
    if phrases:
        parts.append("ФІРМОВІ ФРАЗИ (у цьому стилі спілкуйся):\n" + "\n".join(f"— {p}" for p in phrases[:12]))
    if moves:
        parts.append("ВДАЛІ ПРИЙОМИ:\n" + "\n".join(moves[:max_moves]))
    if objections:
        parts.append("ВІДПРАЦЮВАННЯ ЗАПЕРЕЧЕНЬ:\n" + "\n".join(objections[:max_objections]))
    return "\n\n".join(parts)
