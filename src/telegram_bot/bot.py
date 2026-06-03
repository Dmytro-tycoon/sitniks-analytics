import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from collections import Counter
from src.config import settings
from src.telegram_bot.reports import format_daily_report, format_manager_report
from src.database.supabase_client import get_analyses_by_date, upsert_telegram_user
from src.sitniks.client import SitniksClient

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


async def _fetch_orders_by_manager(date_str: str) -> dict:
    """Тягне замовлення за день і повертає {manager_fullname: count}."""
    from datetime import datetime
    start = datetime.fromisoformat(f"{date_str}T00:00:00+03:00")
    end = start + timedelta(days=1)
    sitniks = SitniksClient()
    try:
        orders = await sitniks.get_orders(start, end)
    finally:
        await sitniks.close()
    return Counter(
        o.get("responsible", {}).get("user", {}).get("fullname")
        for o in orders if o.get("responsible")
    )


async def send_daily_reports(date_str: str = None):
    """Викликається з cron щоранку"""
    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).date().isoformat()

    res = get_analyses_by_date(date_str)
    analyses = res.data

    # Реальна кількість замовлень з Sitniks (по responsible)
    try:
        orders_by_manager = dict(await _fetch_orders_by_manager(date_str))
    except Exception as e:
        print(f"Помилка отримання замовлень: {e}")
        orders_by_manager = {}

    if settings.TELEGRAM_LEADERSHIP_CHAT_ID:
        try:
            await bot.send_message(
                settings.TELEGRAM_LEADERSHIP_CHAT_ID,
                format_daily_report(analyses, orders_by_manager=orders_by_manager),
                parse_mode="HTML",
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
        # Знаходимо число замовлень — повне ім'я в Sitniks може мати суфікс "2"
        m_orders = sum(c for fn, c in orders_by_manager.items() if fn and manager_name.lower() in fn.lower())
        target = shadow or chat_id
        prefix = f"📋 <i>Звіт для {manager_name}</i>\n\n" if shadow else ""
        try:
            await bot.send_message(
                target,
                prefix + format_manager_report(manager_name, m_data, orders_count=m_orders),
                parse_mode="HTML",
            )
        except Exception as e:
            print(f"Помилка надсилання звіту {manager_name}: {e}")


@dp.message()
async def catch_all(message: Message):
    """Запам'ятовуємо будь-кого, хто пише боту, навіть без команди."""
    _remember(message)


async def run_bot():
    print("Telegram-бот запущено")
    await dp.start_polling(bot)
