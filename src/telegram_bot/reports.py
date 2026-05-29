from collections import defaultdict
from typing import List, Dict

MEDALS = ["🥇", "🥈", "🥉", "4."]


def _group_by_manager(analyses: List[Dict]) -> Dict[str, List[Dict]]:
    by_manager = defaultdict(list)
    for a in analyses:
        by_manager[a["manager_name"]].append(a)
    return by_manager


def _avg(items: List[Dict], key: str, default=0) -> float:
    vals = [i.get(key) or 0 for i in items]
    return round(sum(vals) / len(vals), 1) if vals else default


def _criterion_avg(items: List[Dict], crit: str) -> float:
    vals = []
    for i in items:
        s = (i.get("scores") or {}).get(crit) or {}
        if "score" in s:
            vals.append(s["score"])
    return round(sum(vals) / len(vals), 1) if vals else 0


def format_daily_report(analyses: List[Dict]) -> str:
    if not analyses:
        return "📊 За цей день немає діалогів для аналізу."

    date_str = analyses[0]["dialog_date"]
    by_manager = _group_by_manager(analyses)

    total_dialogs = len(analyses)
    total_orders = sum(1 for a in analyses if a.get("has_order"))
    conv = (total_orders / total_dialogs * 100) if total_dialogs else 0
    team_score = _avg(analyses, "overall_score")

    critical_alerts = []
    warning_alerts = []
    for a in analyses:
        for alert in (a.get("alerts") or []):
            entry = {**alert, "manager": a["manager_name"], "client": a.get("client_username")}
            if alert.get("type") == "critical":
                critical_alerts.append(entry)
            else:
                warning_alerts.append(entry)

    lines = [
        f"📊 <b>Звіт за {date_str}</b>",
        "",
        "<b>ЗАГАЛЬНІ ПОКАЗНИКИ</b>",
        f"• Діалогів: <b>{total_dialogs}</b>",
        f"• Замовлень: <b>{total_orders}</b> (Conv {conv:.0f}%)",
        f"• Середня оцінка команди: <b>{team_score}/10</b>",
        f"• Алертів: 🔴 {len(critical_alerts)} | 🟡 {len(warning_alerts)}",
        "",
        "<b>РЕЙТИНГ МЕНЕДЖЕРІВ</b>",
    ]

    ranked = sorted(
        by_manager.items(),
        key=lambda kv: _avg(kv[1], "overall_score"),
        reverse=True,
    )

    for i, (manager, items) in enumerate(ranked):
        medal = MEDALS[i] if i < len(MEDALS) else f"{i+1}."
        score = _avg(items, "overall_score")
        orders = sum(1 for x in items if x.get("has_order"))
        m_conv = orders / len(items) * 100 if items else 0

        # Сильна/слабка сторона
        criteria = ["response_speed", "tone", "needs_discovery", "expertise",
                    "objection_handling", "closing", "upsell"]
        crit_labels = {
            "response_speed": "швидкість", "tone": "тон",
            "needs_discovery": "виявлення потреби", "expertise": "експертність",
            "objection_handling": "заперечення", "closing": "закриття",
            "upsell": "допродаж",
        }
        crit_scores = {c: _criterion_avg(items, c) for c in criteria}
        best = max(crit_scores, key=crit_scores.get)
        worst = min(crit_scores, key=crit_scores.get)

        lines.append(f"\n{medal} <b>{manager}</b>")
        lines.append(f"   Оцінка: <b>{score}/10</b> | Діалогів: {len(items)} | Замовлень: {orders} | Conv: {m_conv:.0f}%")
        lines.append(f"   Сильно: {crit_labels[best]} {crit_scores[best]}/10")
        lines.append(f"   Слабко: {crit_labels[worst]} {crit_scores[worst]}/10")

    if critical_alerts:
        lines.append("\n🚨 <b>КРИТИЧНІ АЛЕРТИ</b>")
        for a in critical_alerts[:5]:
            lines.append(f"• <b>{a['manager']}</b> — {a.get('description', '')[:200]}")
            if a.get("quote"):
                lines.append(f"  «{a['quote'][:150]}»")

    return "\n".join(lines)


def format_manager_report(manager_name: str, analyses: List[Dict], rank: int = None, team_size: int = None) -> str:
    if not analyses:
        return f"👋 Привіт, {manager_name}! За вчора немає аналізованих діалогів."

    date_str = analyses[0]["dialog_date"]
    total = len(analyses)
    orders = sum(1 for a in analyses if a.get("has_order"))
    conv = orders / total * 100 if total else 0
    score = _avg(analyses, "overall_score")

    rank_str = ""
    if rank is not None:
        medal = MEDALS[rank] if rank < 3 else ""
        rank_str = f"\n• Місце в команді: <b>{rank+1}</b>{(' ' + medal) if medal else ''}"

    lines = [
        f"👋 <b>Привіт, {manager_name}!</b> Звіт за {date_str}.",
        "",
        "<b>ТВОЯ СТАТИСТИКА</b>",
        f"• Діалогів: <b>{total}</b>",
        f"• Замовлень: <b>{orders}</b> (Conv {conv:.0f}%)",
        f"• Середня оцінка: <b>{score}/10</b>{rank_str}",
        "",
    ]

    # Топ-3 сильних сторін з найкращого діалогу
    best_dialog = max(analyses, key=lambda a: a.get("overall_score") or 0)
    if best_dialog.get("strengths"):
        lines.append("✅ <b>ЩО БУЛО ОСОБЛИВО ДОБРЕ</b>")
        for s in best_dialog["strengths"][:3]:
            lines.append(f"• {s}")
        lines.append("")

    # Найгірший діалог — зони росту
    worst_dialog = min(analyses, key=lambda a: a.get("overall_score") or 10)
    if worst_dialog.get("improvements"):
        lines.append("⚠️ <b>ЗОНИ РОСТУ</b>")
        for imp in worst_dialog["improvements"][:3]:
            lines.append(f"• {imp}")
        lines.append("")

    # Топ-діалог
    if best_dialog.get("summary"):
        lines.append("🏆 <b>ТВІЙ НАЙКРАЩИЙ ДІАЛОГ</b>")
        client = best_dialog.get("client_username") or best_dialog.get("client_name") or "клієнт"
        lines.append(f"@{client} — {best_dialog['overall_score']}/10")
        lines.append(f"<i>{best_dialog['summary']}</i>")

    return "\n".join(lines)
