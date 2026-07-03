"""Форматери звітів для нових команд (алерти, hot, lost, leaderboard, trends).

Використовуються командами: /alerts, /hot, /lost, /objections, /leaderboard, /trends.
Живуть окремо від існуючих reports.py, щоб не ламати щоденні звіти.
"""
from __future__ import annotations

from src.analyzer.insights import (
    detect_alerts,
    hot_leads,
    leaderboard,
    lost_clients,
    lost_reasons,
    top_objections,
    trends,
)

_ALERT_ICON = {
    "critical": "🚨",
    "hot":      "🔥",
    "negative": "😠",
    "slow":     "🐌",
}


def format_alerts(rows: list[dict]) -> str:
    alerts = detect_alerts(rows)
    if not alerts:
        return "✅ Критичних ситуацій немає."
    lines = [f"⚠️ <b>Потребує уваги ({len(alerts)})</b>"]
    for a in alerts[:20]:
        lines.append(f"{_ALERT_ICON.get(a['kind'], '•')} <b>{a['manager']}</b>: {a['text']}")
    return "\n".join(lines)


def format_leaderboard(rows: list[dict]) -> str:
    board = leaderboard(rows)
    if not board:
        return "Немає даних для рейтингу."
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Рейтинг менеджерів</b>"]
    for i, b in enumerate(board):
        tag = medals[i] if i < 3 else f"{i + 1}."
        lines.append(
            f"{tag} <b>{b['manager']}</b> — {b['avg_score']:.1f}/10 | "
            f"конв. {b['conversion']:.0f}% | діалогів {b['total']}"
        )
    return "\n".join(lines)


def format_hot(rows: list[dict]) -> str:
    hot = hot_leads(rows)
    if not hot:
        return "🔥 Гарячих незакритих лідів немає."
    lines = [f"🔥 <b>Гарячі ліди без замовлення ({len(hot)})</b> — дотиснути:"]
    for r in hot[:20]:
        client = r.get("client_username") or r.get("client_name") or "—"
        summary = (r.get("summary") or "")[:120]
        dialog_id = r.get("dialog_id")
        link = f' <a href="https://web.sitniks.com/2341/chats/dialog/{dialog_id}">чат</a>' if dialog_id else ""
        lines.append(f"• <b>{r.get('manager_name', '—')}</b> → @{client}{link}\n  {summary}")
    return "\n".join(lines)


def format_lost(rows: list[dict]) -> str:
    lost = lost_clients(rows)
    reasons = lost_reasons(rows)
    lines = [f"💔 <b>Втрачені клієнти ({len(lost)})</b>"]
    if reasons:
        lines.append("\n<b>Причини відмов:</b>")
        for reason, cnt in reasons:
            lines.append(f"  • {reason} — {cnt}")
    return "\n".join(lines) if (lost or reasons) else "Втрачених клієнтів не зафіксовано."


def format_objections(rows: list[dict]) -> str:
    objs = top_objections(rows)
    if not objs:
        return "Заперечень у переписках не зафіксовано."
    lines = ["🛡 <b>Топ заперечень клієнтів</b>"]
    for obj, cnt in objs:
        lines.append(f"  • {obj} — {cnt}")
    return "\n".join(lines)


def format_trends(rows: list[dict]) -> str:
    series = trends(rows)
    if not series:
        return "Недостатньо даних для трендів."
    lines = ["📈 <b>Динаміка по тижнях</b>"]
    for s in series:
        lines.append(
            f"  {s['week']}: оцінка {s['avg_score']}/10 | конв. {s['conversion']:.0f}% "
            f"| діалогів {s['dialogs']}"
        )
    return "\n".join(lines)
