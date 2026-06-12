"""
Збір щоденної статистики для таблиці skin.one.hair:
  - Facebook Ads → витрати, покази, кліки
  - Sitniks      → ТО, заявки, продажі (з кешем chat→ownerName у Supabase)
  - Google Sheets → запис результату
"""
import asyncio
import logging
import os
import traceback
from datetime import date, datetime, timedelta

import pytz
from aiogram import Bot

from src.facebook.client import FacebookAdsClient
from src.sitniks.client import SitniksClient
from src.sheets.client import SheetsClient
from src.database import supabase_client as db
from src.config import settings

logger = logging.getLogger(__name__)

# --- константи ---
HAIR_OWNER_NAME = "skin.one.hair"
HAIR_AD_ACCOUNT = "act_1147671684177345"

# Instagram-промоції (фіксована щоденна добавка до Facebook даних)
# Дозволяє override через .env (без редеплою)
INSTAGRAM_DAILY_SPEND       = float(os.getenv("INSTAGRAM_DAILY_SPEND", "310"))
INSTAGRAM_DAILY_IMPRESSIONS = int(os.getenv("INSTAGRAM_DAILY_IMPRESSIONS", "2570"))
INSTAGRAM_DAILY_CLICKS      = int(os.getenv("INSTAGRAM_DAILY_CLICKS", "48"))

# Київська часова зона з підтримкою літнього/зимового часу
KIEV_TZ = pytz.timezone("Europe/Kiev")

# Статуси замовлень, які НЕ враховуємо (скасовані / повернення)
# Перевіряємо за полем status.code (або status.title як fallback)
EXCLUDED_ORDER_STATUS_CODES = {"cancelled", "canceled", "rejected", "refund", "return"}
EXCLUDED_ORDER_STATUS_TITLES = {"Скасовано", "Відмова", "Повернення", "Скасовано клієнтом"}


def _is_excluded_order(order: dict) -> bool:
    """True, якщо замовлення треба пропустити (скасоване / повернене)."""
    status = order.get("status")
    if isinstance(status, dict):
        code = (status.get("code") or "").lower()
        title = status.get("title") or ""
        return code in EXCLUDED_ORDER_STATUS_CODES or title in EXCLUDED_ORDER_STATUS_TITLES
    if isinstance(status, str):
        return status in EXCLUDED_ORDER_STATUS_TITLES
    return False


def _kiev_day_range(target_date: date):
    """Повертає (start_dt, end_dt) для вказаного дня за Київським часом."""
    start = KIEV_TZ.localize(datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0))
    end   = KIEV_TZ.localize(datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59))
    return start, end


async def _resolve_chat_owners(sitniks: SitniksClient, chat_ids: list) -> dict:
    """
    Повертає {chat_id: owner_name}, використовуючи кеш у Supabase.
    Тягне з Sitniks лише ті chat_id, яких нема в кеші.
    """
    if not chat_ids:
        return {}

    # 1. Дістаємо що вже є в кеші
    cached = db.get_cached_chat_owners(chat_ids)
    missing = [cid for cid in chat_ids if cid not in cached]

    logger.info(f"  Chat owners: {len(cached)} з кешу, {len(missing)} тягнемо зі Sitniks")

    if not missing:
        return cached

    # 2. Тягнемо відсутні (з обмеженою concurrency щоб не 429)
    sem = asyncio.Semaphore(2)
    new_owners = {}

    async def fetch_one(chat_id):
        async with sem:
            await asyncio.sleep(0.3)
            try:
                chat = await sitniks.get_chat(chat_id)
                owner = chat.get("ownerName")
                if owner:
                    new_owners[chat_id] = owner
            except Exception as e:
                logger.warning(f"  Помилка отримання чату {chat_id}: {e}")

    await asyncio.gather(*[fetch_one(cid) for cid in missing])

    # 3. Зберігаємо нові в кеш
    if new_owners:
        try:
            db.cache_chat_owners([
                {"chat_id": cid, "owner_name": owner}
                for cid, owner in new_owners.items()
            ])
        except Exception as e:
            logger.warning(f"  Помилка збереження кешу: {e}")

    return {**cached, **new_owners}


async def _get_sitniks_stats(sitniks: SitniksClient, target_date: date) -> dict:
    """Статистика з Sitniks для skin.one.hair за вказану дату."""
    start_dt, end_dt = _kiev_day_range(target_date)

    # 1. Всі замовлення за день (без скасованих)
    all_orders = await sitniks.get_orders(start_dt, end_dt)
    active_orders = [o for o in all_orders if not _is_excluded_order(o)]
    skipped = len(all_orders) - len(active_orders)
    if skipped:
        logger.info(f"  Пропущено {skipped} скасованих/повернутих замовлень")

    # 2. Отримуємо ownerName для всіх chat_id (з кешем)
    chat_ids = list({o["chatId"] for o in active_orders if o.get("chatId")})
    owners = await _resolve_chat_owners(sitniks, chat_ids)

    # 3. Фільтр по skin.one.hair
    hair_orders = [
        o for o in active_orders
        if o.get("chatId") and owners.get(o["chatId"]) == HAIR_OWNER_NAME
    ]

    to_sum = sum(float(o.get("totalPrice", 0)) for o in hair_orders)
    sales_total = len(hair_orders)

    # Маржа і кількість товарів
    margin_sum = 0.0
    products_qty = 0
    for order in hair_orders:
        for product in order.get("products", []):
            price = float(product.get("price", 0))
            cost = float(product.get("costPrice", 0))
            qty = int(product.get("quantity", 1))
            margin_sum += (price - cost) * qty
            products_qty += qty

    # 4. Нові чати skin.one.hair за день
    new_chats_all = await sitniks.get_all_chats(start_dt, end_dt, by_first_message=True)
    new_chats_hair = [c for c in new_chats_all if c.get("ownerName") == HAIR_OWNER_NAME]
    new_chats_count = len(new_chats_hair)

    # 5. Замовлення із діючих чатів
    new_chat_ids = {c["id"] for c in new_chats_hair}
    existing_orders_count = sum(
        1 for o in hair_orders
        if o.get("chatId") and o["chatId"] not in new_chat_ids
    )

    leads = new_chats_count + existing_orders_count

    logger.info(
        f"Sitniks hair {target_date}: ТО={to_sum:.0f}₴ маржа={margin_sum:.0f}₴ "
        f"замовлень={sales_total} товарів={products_qty} "
        f"нових_чатів={new_chats_count} замовл_з_діючих={existing_orders_count} заявок={leads}"
    )

    return {
        "to": round(to_sum, 2),
        "margin": round(margin_sum, 2),
        "leads": leads,
        "sales_total": sales_total,
        "sales_repeat": 0,
        "products_qty": products_qty,
    }


async def _get_fb_stats(fb: FacebookAdsClient, target_date: date) -> dict:
    """Витрати + покази + кліки з Facebook + фіксована добавка з Instagram."""
    data = await fb.get_insights(target_date, target_date)
    logger.info(
        f"Facebook hair {target_date}: spend={data['spend']} imp={data['impressions']} "
        f"clicks={data['inline_link_clicks']}"
    )
    return {
        "fb_spend":       round(data["spend"] + INSTAGRAM_DAILY_SPEND, 2),
        "fb_impressions": data["impressions"] + INSTAGRAM_DAILY_IMPRESSIONS,
        "fb_clicks":      data["inline_link_clicks"] + INSTAGRAM_DAILY_CLICKS,
    }


async def _notify_failure(target_date: date, error: Exception):
    """Сповіщення в групу Керівництво про падіння job-а."""
    chat_id = settings.TELEGRAM_LEADERSHIP_CHAT_ID
    token = settings.TELEGRAM_BOT_TOKEN
    if not (chat_id and token):
        logger.error("Не налаштовано TELEGRAM_LEADERSHIP_CHAT_ID або TELEGRAM_BOT_TOKEN")
        return

    import html
    tb = html.escape(traceback.format_exc()[-1500:])
    err_text = html.escape(f"{type(error).__name__}: {error}")
    msg = (
        f"⚠️ <b>Помилка stats-боту (skin.one.hair)</b>\n"
        f"Дата: <code>{target_date}</code>\n"
        f"Помилка: <code>{err_text}</code>\n\n"
        f"<pre>{tb}</pre>"
    )
    try:
        bot = Bot(token=token)
        await bot.send_message(chat_id, msg[:4000], parse_mode="HTML")
        await bot.session.close()
    except Exception as e:
        logger.error(f"Не вдалось надіслати сповіщення в Telegram: {e}")


async def run_stats_for_date(
    target_date: date,
    fb_token: str,
    sheets: SheetsClient,
    sitniks: SitniksClient = None,
    notify_on_error: bool = True,
) -> dict:
    """Збирає дані за target_date і записує в Google Sheets."""
    try:
        fb = FacebookAdsClient(access_token=fb_token, ad_account_id=HAIR_AD_ACCOUNT)
        if sitniks is None:
            sitniks = SitniksClient()

        sitniks_stats, fb_stats = await asyncio.gather(
            _get_sitniks_stats(sitniks, target_date),
            _get_fb_stats(fb, target_date),
        )

        stats = {**sitniks_stats, **fb_stats}

        success = sheets.write_day_stats(
            month=target_date.month,
            day=target_date.day,
            stats=stats,
        )

        if success:
            logger.info(f"✅ Статистику за {target_date} записано в Google Sheets")
        else:
            raise RuntimeError(f"Не вдалось записати в Sheets за {target_date}")

        return stats

    except Exception as e:
        logger.error(f"❌ Помилка stats-pipeline за {target_date}: {e}", exc_info=True)
        if notify_on_error:
            await _notify_failure(target_date, e)
        raise
