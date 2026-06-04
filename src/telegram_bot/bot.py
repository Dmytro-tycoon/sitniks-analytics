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


@dp.message(Command("start"))
async def cmd_start(message: Message):
    _remember(message)
    await message.answer(
        "👋 Привіт! Я бот аналітики Sitniks.\n\n"
        "Команди:\n"
        "/today — звіт за сьогодні\n"
        "/yesterday — звіт за вчора\n"
        "/manager &lt;ім'я&gt; — звіт по менеджеру (за вчора)\n"
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
            for item in select_review_items(analyses):
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


@dp.message()
async def catch_all(message: Message):
    """Запам'ятовуємо будь-кого, хто пише боту, навіть без команди."""
    _remember(message)


async def run_bot():
    print("Telegram-бот запущено")
    await dp.start_polling(bot)
