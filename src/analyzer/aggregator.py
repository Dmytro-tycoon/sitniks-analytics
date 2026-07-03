"""Зведення оцінок по кожному менеджеру (для консолі та звітів)."""
from __future__ import annotations

from src.claude.sales_prompts import SCORE_KEYS


def aggregate_by_manager(rows: list[dict]) -> dict[str, dict]:
    by: dict[str, dict] = {}
    for a in rows:
        m = a["manager_name"] or "—"
        d = by.setdefault(
            m,
            {"total": 0, "orders": 0, "alerts": [], "scores": {k: [] for k in SCORE_KEYS}, "resp": []},
        )
        d["total"] += 1
        if a.get("has_order"):
            d["orders"] += 1
        for k in SCORE_KEYS:
            v = (a.get("scores") or {}).get(k)
            if v and isinstance(v, dict) and v.get("score") is not None:
                d["scores"][k].append(v["score"])
        d["alerts"].extend(a.get("alerts") or [])
        if a.get("avg_response_minutes") is not None:
            d["resp"].append(a["avg_response_minutes"])

    for m, d in by.items():
        d["conversion"] = (d["orders"] / d["total"] * 100) if d["total"] else 0
        d["avg_scores"] = {k: (sum(v) / len(v)) for k, v in d["scores"].items() if v}
        d["avg_score"] = (
            sum(d["avg_scores"].values()) / len(d["avg_scores"]) if d["avg_scores"] else 0
        )
        d["avg_response"] = (sum(d["resp"]) / len(d["resp"])) if d["resp"] else 0
        d["critical"] = [a for a in d["alerts"] if a.get("type") == "critical"]
    return by
