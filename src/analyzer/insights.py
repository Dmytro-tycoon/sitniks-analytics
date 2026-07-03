"""Інсайти для РОПа: алерти, лідерборд, топ заперечень, причини відмов,
ефективність менеджера, тренди. Чисті функції над рядками аналізу (без API/БД).
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from src.analyzer.aggregator import aggregate_by_manager
from src.claude.sales_prompts import SCORE_LABELS

SLOW_MINUTES = 15.0  # поріг "повільна відповідь"


# ── Блок 1: контроль і алерти ─────────────────────────────────
def hot_leads(rows: list[dict]) -> list[dict]:
    """Клієнт гарячий (high intent), але замовлення немає — треба дотиснути."""
    return [
        r for r in rows
        if (r.get("buying_intent") == "high") and not r.get("has_order")
    ]


def lost_clients(rows: list[dict]) -> list[dict]:
    """Не закрили + є причина втрати."""
    return [r for r in rows if not r.get("has_order") and r.get("lost_reason")]


def detect_alerts(rows: list[dict]) -> list[dict]:
    """Єдиний список того, що потребує уваги керівника зараз."""
    out: list[dict] = []
    for r in rows:
        mgr, did = r.get("manager_name", "—"), r.get("dialog_id", "")
        if r.get("buying_intent") == "high" and not r.get("has_order"):
            out.append({"kind": "hot", "manager": mgr, "dialog_id": did,
                        "text": "Гарячий лід без замовлення — дотиснути"})
        if r.get("client_sentiment") == "negative":
            out.append({"kind": "negative", "manager": mgr, "dialog_id": did,
                        "text": "Негатив клієнта"})
        for a in (r.get("alerts") or []):
            if a.get("type") == "critical":
                out.append({"kind": "critical", "manager": mgr, "dialog_id": did,
                            "text": a.get("description", "")})
        if (r.get("avg_response_minutes") or 0) > SLOW_MINUTES:
            out.append({"kind": "slow", "manager": mgr, "dialog_id": did,
                        "text": f"Повільна відповідь: {r['avg_response_minutes']:.0f} хв"})
    order = {"critical": 0, "hot": 1, "negative": 2, "slow": 3}
    return sorted(out, key=lambda x: order.get(x["kind"], 9))


# ── Блок 2: аналітика РОПа ────────────────────────────────────
def leaderboard(rows: list[dict]) -> list[dict]:
    by = aggregate_by_manager(rows)
    board = [
        {
            "manager": m,
            "avg_score": d["avg_score"],
            "conversion": d["conversion"],
            "total": d["total"],
            "orders": d["orders"],
            "avg_response": d["avg_response"],
        }
        for m, d in by.items()
    ]
    # композитний ранг: якість + конверсія
    board.sort(key=lambda x: (x["avg_score"], x["conversion"]), reverse=True)
    return board


def top_objections(rows: list[dict], n: int = 7) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    for r in rows:
        for o in (r.get("objections") or []):
            if o and isinstance(o, str):
                c[o.strip().lower()] += 1
    return c.most_common(n)


def lost_reasons(rows: list[dict], n: int = 7) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    for r in rows:
        lr = r.get("lost_reason")
        if lr and isinstance(lr, str) and lr.lower() not in ("null", "none"):
            c[lr.strip().lower()] += 1
    return c.most_common(n)


def manager_effectiveness(rows: list[dict], name: str) -> dict:
    """Повна картина по одному менеджеру — для рекомендацій і плану зростання."""
    mine = [r for r in rows if r.get("manager_name") == name]
    if not mine:
        return {}
    d = aggregate_by_manager(mine)[name]
    scores = d["avg_scores"]
    weakest = sorted(scores.items(), key=lambda x: x[1])[:3]
    strongest = sorted(scores.items(), key=lambda x: -x[1])[:3]
    return {
        "manager": name,
        "total": d["total"],
        "orders": d["orders"],
        "conversion": round(d["conversion"], 1),
        "avg_score": round(d["avg_score"], 1),
        "avg_response": round(d["avg_response"], 1),
        "weakest": [{"area": SCORE_LABELS.get(k, k), "score": round(v, 1)} for k, v in weakest],
        "strongest": [{"area": SCORE_LABELS.get(k, k), "score": round(v, 1)} for k, v in strongest],
        "top_objections": top_objections(mine, 5),
        "lost_reasons": lost_reasons(mine, 5),
        "recommendations_seen": [r.get("recommendation") for r in mine if r.get("recommendation")][:5],
    }


def _week_key(d: str | date | datetime) -> str:
    if isinstance(d, str):
        d = datetime.fromisoformat(d).date()
    if isinstance(d, datetime):
        d = d.date()
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def trends(rows: list[dict]) -> list[dict]:
    """Динаміка по тижнях: середня оцінка і конверсія. Видно, хто росте/падає."""
    by_week: dict[str, list[dict]] = {}
    for r in rows:
        by_week.setdefault(_week_key(r["dialog_date"]), []).append(r)
    series = []
    for wk in sorted(by_week):
        wk_rows = by_week[wk]
        agg = aggregate_by_manager(wk_rows)
        scores = [d["avg_score"] for d in agg.values() if d["avg_score"]]
        orders = sum(d["orders"] for d in agg.values())
        total = sum(d["total"] for d in agg.values())
        series.append({
            "week": wk,
            "dialogs": total,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "conversion": round(orders / total * 100, 1) if total else 0,
        })
    return series
