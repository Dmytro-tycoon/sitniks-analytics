import asyncio
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    ForceReply,
)

from collections import Counter
from src.config import settings
from src.telegram_bot.reports import (
    format_daily_report, format_manager_report, format_review_item, select_review_items,
)
from src.database.supabase_client import (
    get_analyses_by_date, upsert_telegram_user, save_feedback, get_analysis,
)
from src.sitniks.client import SitniksClient


def _review_keyboard(dialog_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Згоден", callback_data=f"fb:agree:{dialog_id}"),
        InlineKeyboardButton(text="❌ Не згоден", callback_data=f"fb:disagree:{dialog_id}"),
    ]])

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()


def _remember(message: Message):
    import sys
    print(f"[remember] chat_id={message.chat.id} from={message.from_user.username if message.from_user else None}", flush=True)
    try:
        upsert_telegram_user(
            chat_id=message.chat.id,
            username=message.from_user.username if message.from_user else None,
            first_name=message.from_user.first_name if message.from_user else None,
            last_name=message.from_user.last_name if message.from_user else None,
            chat_type=message.chat.type,
            chat_title=message.chat.title,
        )
        print(f"[remember] saved OK: {message.chat.id}", flush=True)
    except Exception as e:
        print(f"[remember] FAILED for {message.chat.id}: {type(e).__name__}: {e}", flush=True)
        import traceback; traceback.print_exc()
        sys.stdout.flush()


@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    _remember(message)
    await message.answer(
        "👋 Я аналізую переписки менеджерів і допомагаю керувати відділом продажів.\n\n"
        "<b>📊 Звіти</b>\n"
        "/today, /yesterday — звіт за день\n"
        "/manager Ім'я — розбір менеджера\n"
        "/leaderboard — рейтинг менеджерів (7 днів)\n"
        "/trends — динаміка по тижнях\n\n"
        "<b>🚨 Контроль</b>\n"
        "/alerts — що потребує уваги зараз\n"
        "/hot — гарячі ліди без замовлення\n"
        "/lost — втрачені клієнти і причини\n"
        "/objections — топ заперечень\n\n"
        "<b>🤝 Поради (Claude)</b>\n"
        "/reco Ім'я — рекомендації по менеджеру\n"
        "/plan Ім'я — план зростання менеджера\n"
        "/objection текст — як відповісти на заперечення\n\n"
        "<b>🧠 База знань</b>\n"
        "/ask питання — відповідь по всіх переписках\n"
        "/faq — часті питання клієнтів\n\n"
        "<b>⚙️ Сервісне</b>\n"
        "/whoami — мій chat_id",
        parse_mode="HTML",
    )


@dp.message(Command("whoami"))
async def cmd_whoami(message: Message):
    _remember(message)
    await message.answer(
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"type: {message.chat.type}\n"
        f"title: {message.chat.title or '-'}",
        parse_mode="HTML",
    )


@dp.message(Command("today"))
async def cmd_today(message: Message):
    today = datetime.now().date().isoformat()
    res = get_analyses_by_date(today)
    await message.answer(format_daily_report(res.data), parse_mode="HTML")


@dp.message(Command("yesterday"))
async def cmd_yesterday(message: Message):
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    res = get_analyses_by_date(yesterday)
    await message.answer(format_daily_report(res.data), parse_mode="HTML")


@dp.message(Command("manager"))
async def cmd_manager(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Використання: /manager Ім'я")
        return

    name = parts[1].strip()
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    res = get_analyses_by_date(yesterday)
    manager_data = [a for a in res.data if name.lower() in a["manager_name"].lower()]

    if not manager_data:
        await message.answer(f"Не знайдено діалогів за {yesterday} для «{name}»")
        return

    await message.answer(format_manager_report(name, manager_data), parse_mode="HTML")


async def _fetch_day_stats(date_str: str) -> dict:
    """Тягне нові чати, замовлення; рахує per-manager: новi+діючі-з-замовленням і orders."""
    from datetime import datetime
    start = datetime.fromisoformat(f"{date_str}T00:00:00+03:00")
    end = start + timedelta(days=1)
    sitniks = SitniksClient()
    try:
        new_chats = await sitniks.get_all_chats(start, end, by_first_message=True)
        orders = await sitniks.get_orders(start, end)
    finally:
        await sitniks.close()

    new_ids = {c["id"] for c in new_chats}
    orders_by_manager = Counter()
    new_by_manager = Counter()
    existing_with_order_by_manager = Counter()

    for c in new_chats:
        m = c.get("assignedManagerName")
        if m:
            new_by_manager[m] += 1

    for o in orders:
        m = o.get("responsible", {}).get("user", {}).get("fullname")
        if not m:
            continue
        orders_by_manager[m] += 1
        chat_id = o.get("chatId")
        if chat_id and chat_id not in new_ids:
            existing_with_order_by_manager[m] += 1

    # Загальна кількість діалогів = нові + діючі з замовленням
    total_by_manager = {m: new_by_manager[m] + existing_with_order_by_manager[m]
                        for m in set(list(new_by_manager) + list(existing_with_order_by_manager))}

    return {
        "orders": dict(orders_by_manager),
        "new_chats": dict(new_by_manager),
        "existing_with_order": dict(existing_with_order_by_manager),
        "total_chats": total_by_manager,
    }


async def send_daily_reports(date_str: str = None):
    """Викликається з cron щоранку"""
    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).date().isoformat()

    res = get_analyses_by_date(date_str)
    analyses = res.data

    # Статистика з Sitniks (orders + new chats)
    try:
        stats = await _fetch_day_stats(date_str)
    except Exception as e:
        print(f"Помилка отримання статистики Sitniks: {e}")
        stats = {"orders": {}, "new_chats": {}, "existing_with_order": {}, "total_chats": {}}
    orders_by_manager = stats["orders"]

    if settings.TELEGRAM_LEADERSHIP_CHAT_ID:
        try:
            await bot.send_message(
                settings.TELEGRAM_LEADERSHIP_CHAT_ID,
                format_daily_report(analyses, orders_by_manager=orders_by_manager, total_chats_by_manager=stats["total_chats"]),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            # Окремі повідомлення з кнопками — для good/bad прикладів
            for item in select_review_items(analyses, top_good=2, top_bad=3):
                await bot.send_message(
                    settings.TELEGRAM_LEADERSHIP_CHAT_ID,
                    format_review_item(item),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_markup=_review_keyboard(item["dialog_id"]),
                )
        except Exception as e:
            print(f"Помилка надсилання звіту керівництву: {e}")

    # Особисті звіти. Якщо TELEGRAM_SHADOW_CHAT_ID встановлено -
    # перенаправляємо всі звіти туди (для preview перед запуском менеджерам)
    managers_map = settings.TELEGRAM_MANAGERS
    shadow = settings.TELEGRAM_SHADOW_CHAT_ID
    for manager_name, chat_id in managers_map.items():
        m_data = [a for a in analyses if manager_name.lower() in a["manager_name"].lower()]
        if not m_data:
            continue
        # Знаходимо число замовлень і діалогів — повне ім'я в Sitniks може мати суфікс "2"
        m_orders = sum(c for fn, c in orders_by_manager.items() if fn and manager_name.lower() in fn.lower())
        m_total_chats = sum(c for fn, c in stats["total_chats"].items() if fn and manager_name.lower() in fn.lower())
        target = shadow or chat_id
        prefix = f"📋 <i>Звіт для {manager_name}</i>\n\n" if shadow else ""
        try:
            await bot.send_message(
                target,
                prefix + format_manager_report(manager_name, m_data, orders_count=m_orders, total_chats=m_total_chats),
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"Помилка надсилання звіту {manager_name}: {e}")


@dp.callback_query(F.data.startswith("fb:"))
async def cb_feedback(cb: CallbackQuery):
    """Обробка кнопок Згоден/Не згоден під review-діалогом."""
    try:
        _, action, dialog_id = cb.data.split(":", 2)
    except ValueError:
        await cb.answer("Bad callback")
        return

    rec = get_analysis(dialog_id)
    if not rec:
        await cb.answer("Діалог не знайдено")
        return

    if action == "agree":
        save_feedback(dialog_id, confirmed=True)
        await cb.message.edit_text(
            (cb.message.html_text or "") + "\n\n<b>✅ Підтверджено</b>",
            parse_mode="HTML",
        )
        await cb.answer("Зараховано")
    elif action == "disagree":
        save_feedback(dialog_id, confirmed=False)
        # Просимо коментар через ForceReply
        await cb.message.edit_text(
            (cb.message.html_text or "") + "\n\n<b>❌ Не згоден</b>",
            parse_mode="HTML",
        )
        await cb.message.reply(
            f"Напиши <b>reply</b> на це повідомлення з коментарем:\n"
            f"чому цей діалог насправді нормальний/інший?\n\n"
            f"🆔 <code>{dialog_id}</code>",
            parse_mode="HTML",
            reply_markup=ForceReply(selective=True, input_field_placeholder="Твій коментар…"),
        )
        await cb.answer("Чекаю на коментар")


_COMMENT_ID_RE = re.compile(r"🆔\s*([0-9a-f]{24})")


@dp.message(F.reply_to_message)
async def cb_comment(message: Message):
    """Обробка reply на ForceReply: записуємо коментар у БД."""
    rtm = message.reply_to_message
    text = rtm.text or rtm.caption or ""
    m = _COMMENT_ID_RE.search(text)
    if not m:
        # Не наш ForceReply — обробляємо як звичайне повідомлення
        _remember(message)
        return
    dialog_id = m.group(1)
    save_feedback(dialog_id, confirmed=False, comment=message.text)
    await message.reply(f"💾 Коментар збережено для <code>{dialog_id}</code>", parse_mode="HTML")


# ══ Sales-agent інтеграція ═══════════════════════════════════════════════
# Нові команди від Dreammarketing/sales-agent:
# /alerts /hot /lost /objections /leaderboard /trends
# /reco /plan /objection /ask /faq
from src.analyzer.insights import manager_effectiveness
from src.coach.advisor import (
    growth_plan as _growth_plan,
    handle_objection as _handle_objection,
    manager_recommendations as _manager_recommendations,
    suggest_reply as _suggest_reply,
)
from src.rag.knowledge import ask as _rag_ask, build_faq as _build_faq
from src.database.supabase_client import get_analyses_range
from src.telegram_bot.insights_reports import (
    format_alerts as _fmt_alerts,
    format_leaderboard as _fmt_leaderboard,
    format_hot as _fmt_hot,
    format_lost as _fmt_lost,
    format_objections as _fmt_objections,
    format_trends as _fmt_trends,
)
import pytz


def _recent_rows(days: int) -> list:
    """Плоский список аналізів за N днів (для insights/coach/rag)."""
    tz = pytz.timezone(settings.ANALYSIS_TIMEZONE)
    today = datetime.now(tz).date()
    start = (today - timedelta(days=days)).isoformat()
    return get_analyses_range(start, today.isoformat())


def _today_rows() -> list:
    tz = pytz.timezone(settings.ANALYSIS_TIMEZONE)
    d = datetime.now(tz).date().isoformat()
    return get_analyses_by_date(d).data


@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message):
    _remember(message)
    await message.answer(_fmt_leaderboard(_recent_rows(7)), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("trends"))
async def cmd_trends(message: Message):
    _remember(message)
    await message.answer(_fmt_trends(_recent_rows(56)), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("alerts"))
async def cmd_alerts(message: Message):
    _remember(message)
    await message.answer(_fmt_alerts(_today_rows()), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("hot"))
async def cmd_hot(message: Message):
    _remember(message)
    await message.answer(_fmt_hot(_recent_rows(3)), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("lost"))
async def cmd_lost(message: Message):
    _remember(message)
    await message.answer(_fmt_lost(_recent_rows(7)), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("objections"))
async def cmd_objections(message: Message):
    _remember(message)
    await message.answer(_fmt_objections(_recent_rows(7)), parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("reco"))
async def cmd_reco(message: Message):
    _remember(message)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Використання: <code>/reco Ім'я</code>", parse_mode="HTML")
        return
    name = parts[1].strip()
    eff = manager_effectiveness(_recent_rows(30), name)
    if not eff:
        await message.answer("Немає даних по цьому менеджеру за 30 днів.")
        return
    try:
        res = await _manager_recommendations(name, eff)
    except Exception as e:
        await message.answer(f"❌ Помилка Claude: {e}")
        return
    recs = res.get("recommendations") or []
    txt = "💡 <b>Рекомендації для " + name + "</b>\n" + "\n".join(f"• {r}" for r in recs)
    await message.answer(txt, parse_mode="HTML")


@dp.message(Command("plan"))
async def cmd_plan(message: Message):
    _remember(message)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Використання: <code>/plan Ім'я</code>", parse_mode="HTML")
        return
    name = parts[1].strip()
    eff = manager_effectiveness(_recent_rows(30), name)
    if not eff:
        await message.answer("Немає даних по цьому менеджеру за 30 днів.")
        return
    try:
        res = await _growth_plan(name, eff)
    except Exception as e:
        await message.answer(f"❌ Помилка Claude: {e}")
        return
    lines = [f"📈 <b>План зростання: {name}</b>"]
    for f in (res.get("focuses") or []):
        lines.append(f"• <b>{f.get('area','')}</b>: {f.get('action','')}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(Command("objection"))
async def cmd_objection(message: Message):
    _remember(message)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Використання: <code>/objection дорого</code>", parse_mode="HTML")
        return
    try:
        res = await _handle_objection(parts[1].strip())
    except Exception as e:
        await message.answer(f"❌ Помилка Claude: {e}")
        return
    replies = res.get("replies") or []
    await message.answer("🛡 <b>Варіанти відповіді:</b>\n\n" + "\n\n".join(replies), parse_mode="HTML")


@dp.message(Command("ask"))
async def cmd_ask(message: Message):
    _remember(message)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Використання: <code>/ask де клієнти злились на ціні</code>", parse_mode="HTML")
        return
    try:
        res = await _rag_ask(parts[1].strip(), _recent_rows(30))
    except Exception as e:
        await message.answer(f"❌ Помилка Claude: {e}")
        return
    text = "🧠 " + (res.get("answer") or "—")
    for c in (res.get("citations") or [])[:5]:
        text += f"\n\n<i>{c.get('manager','—')}: «{c.get('quote','')}»</i>"
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@dp.message(Command("faq"))
async def cmd_faq(message: Message):
    _remember(message)
    try:
        res = await _build_faq(_recent_rows(30))
    except Exception as e:
        await message.answer(f"❌ Помилка Claude: {e}")
        return
    faq = res.get("faq") or []
    if not faq:
        await message.answer("Поки недостатньо даних для FAQ.")
        return
    lines = ["❓ <b>Часті питання клієнтів:</b>"]
    for q in faq:
        lines.append(f"\n<b>{q.get('question','')}</b> ({q.get('how_often','')})\n{q.get('good_answer','')}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message()
async def catch_all(message: Message):
    """Запам'ятовуємо будь-кого, хто пише боту, навіть без команди."""
    _remember(message)


async def run_bot():
    print("Telegram-бот запущено")
    await dp.start_polling(bot)
