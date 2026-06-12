"""
Окремий Telegram-бот для звіту по рекламних постах.
Команди:
  /ads          — звіт за вчора
  /ads YYYY-MM-DD — звіт за конкретну дату
  /ads_today    — звіт за сьогодні (наживо)
  /whoami       — chat_id
"""
from datetime import datetime, timedelta
import pytz

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from src.config import settings
from src.analyzer.ad_analytics import build_ad_report, format_ad_report, mark_report_as_sent
from src.database.supabase_client import get_client

KIEV_TZ = pytz.timezone("Europe/Kiev")

ads_bot = Bot(
    token=settings.ADS_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
ads_dp = Dispatcher()


def _parse_date(arg: str) -> datetime:
    """YYYY-MM-DD → datetime у KIEV_TZ опівночі."""
    d = datetime.strptime(arg.strip(), "%Y-%m-%d")
    return KIEV_TZ.localize(d.replace(hour=0, minute=0, second=0, microsecond=0))


async def _send_report(message: Message, date_from: datetime, date_to: datetime, label: str):
    await message.answer(f"⏳ Збираю дані за {label}...")
    try:
        report = await build_ad_report(date_from, date_to)
        text = format_ad_report(report)
        # Telegram message limit ~4096 chars
        for chunk in _chunks(text, 4000):
            await message.answer(chunk, disable_web_page_preview=True)
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")


def _chunks(text: str, size: int):
    lines = text.split("\n")
    buf = []
    cur = 0
    for ln in lines:
        if cur + len(ln) + 1 > size and buf:
            yield "\n".join(buf)
            buf, cur = [], 0
        buf.append(ln)
        cur += len(ln) + 1
    if buf:
        yield "\n".join(buf)


@ads_dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Це бот аналітики рекламних постів.\n\n"
        "<b>Команди:</b>\n"
        "• /ads — звіт за вчора\n"
        "• /ads YYYY-MM-DD — звіт за конкретну дату\n"
        "• /ads_today — звіт за сьогодні\n"
        "• /whoami — твій chat_id"
    )


@ads_dp.message(Command("whoami"))
async def cmd_whoami(message: Message):
    await message.answer(
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"type: {message.chat.type}\n"
        f"title: {message.chat.title or message.chat.full_name or '—'}"
    )


@ads_dp.message(Command("ads"))
async def cmd_ads(message: Message, command: CommandObject):
    if command.args:
        try:
            date_from = _parse_date(command.args)
        except ValueError:
            await message.answer("❌ Формат дати: /ads 2026-06-04")
            return
        label = date_from.strftime("%d.%m.%Y")
    else:
        now = datetime.now(KIEV_TZ)
        date_from = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        label = f"вчора ({date_from.strftime('%d.%m.%Y')})"

    date_to = date_from + timedelta(days=1)
    await _send_report(message, date_from, date_to, label)


@ads_dp.message(Command("ads_today"))
async def cmd_ads_today(message: Message):
    now = datetime.now(KIEV_TZ)
    date_from = now.replace(hour=0, minute=0, second=0, microsecond=0)
    await _send_report(message, date_from, now, f"сьогодні ({date_from.strftime('%d.%m.%Y')}, наживо)")


async def send_daily_ads_report():
    """Виклик з cron: тиха розсилка за вчора у ADS_REPORT_CHAT_ID."""
    chat_id = settings.ADS_REPORT_CHAT_ID
    if not chat_id:
        print("⚠️ ADS_REPORT_CHAT_ID не задано — пропускаю розсилку")
        return

    now = datetime.now(KIEV_TZ)
    date_from = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date_from + timedelta(days=1)

    try:
        report = await build_ad_report(date_from, date_to, exclude_reported=True)
        if report["total"] == 0:
            print(f"[ads_bot] no new orders to report (skipped {report['skipped_already_reported']})")
            return
        text = format_ad_report(report)
        for chunk in _chunks(text, 4000):
            await ads_bot.send_message(chat_id, chunk, disable_web_page_preview=True)
        marked = mark_report_as_sent(report)
        print(f"[ads_bot] daily report sent → {chat_id} (marked {marked} orders as reported)")
    except Exception as e:
        print(f"[ads_bot] daily report FAILED: {e}")


async def reattribute_yesterday(target_date: datetime = None, dry_run: bool = False) -> dict:
    """
    Перерахунок атрибуції для замовлень за target_date (default = вчора).

    Sitniks заповнює adInfo у повідомленнях із затримкою (~годинами), тому
    о 08:00 деякі замовлення можуть мати застарілу атрибуцію. Цей job
    запускається пізніше (22:00) — коли всі adInfo синхронізувалися — і:
      1. Перераховує атрибуцію для всіх замовлень за target_date
      2. Знаходить різниці з reported_ad_orders
      3. Оновлює БД і надсилає коригуючий алерт у групу

    Якщо різниць немає — нічого не надсилає.
    Повертає dict зі статистикою (diffs, updated, etc).
    """
    chat_id = settings.ADS_REPORT_CHAT_ID

    if target_date is None:
        target_date = (datetime.now(KIEV_TZ) - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    date_from = target_date
    date_to = date_from + timedelta(days=1)
    label = date_from.strftime("%d.%m.%Y")

    # Свіжа атрибуція (без exclude_reported)
    fresh = await build_ad_report(date_from, date_to)
    fresh_map = {o["id"]: t for o, t in fresh["orders_resolved"]}

    # Старі дані з БД
    res = get_client().table("reported_ad_orders") \
        .select("order_id, ad_title, chat_id") \
        .eq("order_date", date_from.date().isoformat()) \
        .execute()
    old_map = {row["order_id"]: row["ad_title"] for row in (res.data or [])}

    # Знаходимо diff (тільки серед тих, що вже надсилались)
    diffs = []
    for oid, new_title in fresh_map.items():
        old_title = old_map.get(oid)
        if old_title is None:
            continue  # це замовлення не було у попередньому звіті — пропускаємо
        if old_title != new_title:
            diffs.append({"order_id": oid, "old": old_title, "new": new_title})

    print(f"[reattribute] {label}: {len(diffs)} diffs (of {len(old_map)} previously reported)")

    if not diffs:
        return {"diffs": 0, "updated": 0}

    if dry_run:
        return {"diffs": len(diffs), "updated": 0, "details": diffs}

    # Оновлюємо БД
    rows_to_upsert = []
    for d in diffs:
        # знайдемо chat_id серед свіжих
        order = next((o for o, t in fresh["orders_resolved"] if o["id"] == d["order_id"]), None)
        rows_to_upsert.append({
            "order_id": d["order_id"],
            "ad_title": d["new"],
            "order_date": (order.get("createdAt") or "")[:10] if order else date_from.date().isoformat(),
            "chat_id": order.get("chatId") if order else None,
        })
    get_client().table("reported_ad_orders").upsert(
        rows_to_upsert, on_conflict="order_id"
    ).execute()

    # Формуємо коригуючий алерт
    lines = [
        f"🔄 <b>Коригування атрибуції за {label}</b>",
        f"Sitniks заповнив <code>adInfo</code> із затримкою — оновлено <b>{len(diffs)}</b> запис(ів):",
        "",
    ]
    for d in diffs:
        lines.append(f"order <code>{d['order_id']}</code>")
        lines.append(f"  було: {d['old']}")
        lines.append(f"  стало: <b>{d['new']}</b>")
        lines.append("")

    if chat_id:
        text = "\n".join(lines)
        for chunk in _chunks(text, 4000):
            await ads_bot.send_message(chat_id, chunk, disable_web_page_preview=True)
        print(f"[reattribute] correction alert sent → {chat_id}")

    return {"diffs": len(diffs), "updated": len(rows_to_upsert)}
