from collections import defaultdict
from typing import List, Dict

MEDALS = ["🥇", "🥈", "🥉", "4."]
SITNIKS_COMPANY_ID = "2341"


def _format_client(rec: dict) -> str:
    """
    Повертає рядок з даними клієнта для пошуку в Sitniks:
    "Tetiana Rybalka (@tetiana_rybalka) [відкрити]"
    Якщо нема імені — лише нік. Прямий лінк відкриває чат у Sitniks.
    """
    name = (rec.get("client_name") or "").strip()
    nick = (rec.get("client_username") or "").strip()
    chat_id = rec.get("dialog_id")

    if name and nick:
        display = f"{name} (@{nick})"
    elif name:
        display = name
    elif nick:
        display = f"@{nick}"
    else:
        display = "—"

    if chat_id:
        link = f'https://web.sitniks.com/{SITNIKS_COMPANY_ID}/chats/dialog/{chat_id}'
        return f'<a href="{link}">{display}</a>'
    return display


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


def format_daily_report(analyses: List[Dict], orders_by_manager: Dict[str, int] = None,
                         total_chats_by_manager: Dict[str, int] = None) -> str:
    if not analyses:
        return "📊 За цей день немає діалогів для аналізу."

    orders_by_manager = orders_by_manager or {}
    total_chats_by_manager = total_chats_by_manager or {}
    date_str = analyses[0]["dialog_date"]

    # Розділяємо аналізовані і пропущені (скіпнуті short-діалоги без оцінки)
    analyzed = [a for a in analyses if a.get("overall_score") is not None]
    skipped = [a for a in analyses if a.get("overall_score") is None]

    by_manager = _group_by_manager(analyzed)

    total_dialogs = sum(total_chats_by_manager.values()) if total_chats_by_manager else len(analyses)
    total_orders = sum(orders_by_manager.values())
    conv = (total_orders / total_dialogs * 100) if total_dialogs else 0
    team_score = _avg(analyzed, "overall_score") if analyzed else 0

    critical_alerts = []
    warning_alerts = []
    for a in analyzed:
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
        f"• Діалогів: <b>{total_dialogs}</b> (проаналізовано {len(analyzed)}, короткі/skip {len(skipped)})",
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
        # Шукаємо менеджера (з урахуванням можливого суфіксу "2")
        orders = sum(c for fn, c in orders_by_manager.items() if fn and manager.lower() in fn.lower())
        dialogs = sum(c for fn, c in total_chats_by_manager.items() if fn and manager.lower() in fn.lower()) or len(items)
        m_conv = orders / dialogs * 100 if dialogs else 0

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
        lines.append(f"   Оцінка: <b>{score}/10</b> | Діалогів: {dialogs} | Замовлень: {orders} | Conv: {m_conv:.0f}%")
        lines.append(f"   Сильно: {crit_labels[best]} {crit_scores[best]}/10")
        lines.append(f"   Слабко: {crit_labels[worst]} {crit_scores[worst]}/10")

    if critical_alerts:
        lines.append("\n🚨 <b>КРИТИЧНІ АЛЕРТИ</b>")
        for a in critical_alerts[:5]:
            lines.append(f"• <b>{a['manager']}</b> — {a.get('description', '')[:200]}")
            if a.get("quote"):
                lines.append(f"  «{a['quote'][:150]}»")

    # 🏆 Топ-3 хороші діалоги для прикладу
    good = sorted([a for a in analyzed if a.get("dialog_quality") == "good"],
                  key=lambda a: a.get("overall_score") or 0, reverse=True)[:3]
    # Хороші/погані виносимо як окремі повідомлення з кнопками — не в загальний текст

    # Окремо: чати де КЛІЄНТ ПИСАВ, але менеджер не відповів жодного слова
    # (виключаємо порожні чати без клієнтських повідомлень)
    ignored = [
        a for a in skipped
        if (a.get("messages_from_manager") or 0) == 0
        and (a.get("messages_count") or 0) > 0
    ]
    if ignored:
        lines.append(f"\n🔇 <b>МЕНЕДЖЕР НЕ ВІДПОВІВ</b> ({len(ignored)})")
        # Групуємо за менеджером якому призначено чат
        by_assigned = {}
        for a in ignored:
            by_assigned.setdefault(a["manager_name"], []).append(a)
        for manager, items in sorted(by_assigned.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"• <b>{manager}</b> — {len(items)} чат(ів)")
            for i in items[:5]:
                lines.append(f"   ↳ {_format_client(i)} (msg клієнта: {i.get('messages_count', 0)})")

    return "\n".join(lines)


def format_review_item(a: Dict) -> str:
    """Окреме повідомлення для review (одного good/bad діалогу) — буде з кнопками."""
    q = a.get("dialog_quality")
    icon = "🏆" if q == "good" else "💔"
    label = "ХОРОШИЙ ПРИКЛАД" if q == "good" else "ДЛЯ РОЗБОРУ"
    score = a.get("overall_score", "?")
    reason = a.get("quality_reason") or ""
    return (
        f"{icon} <b>{label}</b>\n"
        f"<b>{a['manager_name']}</b> → {_format_client(a)} — {score}/10\n"
        f"{reason[:400]}"
    )


def select_review_items(analyses: List[Dict], top_good: int = 3, top_bad: int = 3) -> List[Dict]:
    """Повертає список діалогів для надсилання як окремі повідомлення з кнопками."""
    analyzed = [a for a in analyses if a.get("overall_score") is not None]
    good = sorted([a for a in analyzed if a.get("dialog_quality") == "good"],
                  key=lambda a: a.get("overall_score") or 0, reverse=True)[:top_good]
    bad = sorted([a for a in analyzed if a.get("dialog_quality") == "bad"],
                 key=lambda a: a.get("overall_score") or 10)[:top_bad]
    return good + bad


def format_manager_report(manager_name: str, analyses: List[Dict], rank: int = None,
                           team_size: int = None, orders_count: int = None, total_chats: int = None) -> str:
    if not analyses:
        return f"👋 Привіт, {manager_name}! За вчора немає аналізованих діалогів."

    date_str = analyses[0]["dialog_date"]
    total = total_chats if total_chats else len(analyses)
    orders = orders_count if orders_count is not None else sum(1 for a in analyses if a.get("has_order"))
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
        lines.append(f"{_format_client(best_dialog)} — {best_dialog['overall_score']}/10")
        lines.append(f"<i>{best_dialog['summary']}</i>")

    return "\n".join(lines)
