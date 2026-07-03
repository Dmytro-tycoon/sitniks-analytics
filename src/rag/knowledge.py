"""Блок 4: база знань по перепискам.

Пошук без зовнішнього embeddings-провайдера: легкий лексичний скоринг по збережених
розборах діалогів → top-N передаємо Claude для відповіді з цитатами.
(Семантичний пошук на pgvector — точка розширення у Фазі 2+.)
"""
from __future__ import annotations

import re

from src.claude.llm import complete_json
from src.claude.sales_prompts import FAQ_PROMPT, RAG_ANSWER_PROMPT


def _searchable_text(row: dict) -> str:
    parts = [
        row.get("summary") or "",
        row.get("recommendation") or "",
        " ".join(row.get("objections") or []),
        row.get("lost_reason") or "",
        row.get("manager_name") or "",
    ]
    return " ".join(parts).lower()


def _tokens(s: str) -> list[str]:
    return re.findall(r"\w+", s.lower())


def retrieve(question: str, rows: list[dict], n: int = 8) -> list[dict]:
    """Чиста функція: повертає найрелевантніші діалоги за збігом слів запиту."""
    q = set(t for t in _tokens(question) if len(t) > 2)
    scored = []
    for r in rows:
        text = _searchable_text(r)
        score = sum(text.count(t) for t in q)
        if score:
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:n]]


def _format_context(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        lines.append(
            f"[{r.get('manager_name', '—')} | {r.get('dialog_date', '')}] "
            f"{r.get('summary', '')} "
            f"Заперечення: {', '.join(r.get('objections') or []) or '—'}."
        )
    return "\n".join(lines)


async def ask(question: str, rows: list[dict]) -> dict:
    """Відповідь на питання РОПа по перепискам, з цитатами."""
    found = retrieve(question, rows)
    if not found:
        return {"answer": "За цим запитом у переписках нічого не знайдено.", "citations": []}
    return await complete_json(
        RAG_ANSWER_PROMPT.format(question=question, context=_format_context(found))
    )


async def build_faq(rows: list[dict]) -> dict:
    """Автоматичний FAQ із заперечень/питань клієнтів у переписках."""
    questions = []
    for r in rows:
        questions.extend(r.get("objections") or [])
        if r.get("summary"):
            questions.append(r["summary"])
    if not questions:
        return {"faq": []}
    return await complete_json(FAQ_PROMPT.format(questions="\n".join(f"- {q}" for q in questions[:80])))
