"""
Збір щоденної статистики для таблиці skin.one.hair:
  - Facebook Ads → витрати, покази, кліки
  - Sitniks      → ТО, заявки, продажі
  - Google Sheets → запис результату
"""
import asyncio
import logging
from datetime import date, datetime, timezone, timedelta

from src.facebook.client import FacebookAdsClient
from src.sitniks.client import SitniksClient
from src.sheets.client import SheetsClient

logger = logging.getLogger(__name__)

# --- константи ---
HAIR_OWNER_NAME = "skin.one.hair"
HAIR_AD_ACCOUNT = "act_1147671684177345"

KIEV_TZ = timezone(timedelta(hours=3))


def _kiev_day_range(target_date: date):
    """Повертає (start_dt, end_dt) для вказаного дня за Київським часом."""
    start = datetime(target_date.year, target_date.month, target_date.day,
                     0, 0, 0, tzinfo=KIEV_TZ)
    end = datetime(target_date.year, target_date.month, target_date.day,
                   23, 59, 59, tzinfo=KIEV_TZ)
    return start, end


async def _get_sitniks_stats(sitniks: SitniksClient, target_date: date) -> dict:
    """
    Повертає статистику з Sitniks для skin.one.hair за вказану дату:
    - to:           сума замовлень (грн)
    - leads:        нові чати + к-сть замовлень із діючих чатів
    - sales_total:  загальна кількість замовлень
    """
    start_dt, end_dt = _kiev_day_range(target_date)

    # 1. Всі замовлення за день
    all_orders = await sitniks.get_orders(start_dt, end_dt)

    # 2. Для кожного замовлення беремо чат → фільтруємо по ownerName
    hair_orders = []
    tasks = []

    async def fetch_chat_and_check(order):
        chat_id = order.get("chatId")
        if not chat_id:
            return None
        try:
            chat = await sitniks.get_chat(chat_id)
            if chat.get("ownerName") == HAIR_OWNER_NAME:
                return order
        except Exception as e:
            logger.warning(f"Помилка отримання чату {chat_id}: {e}")
        return None

    # Concurrency обмежена через семафор (щоб не 429)
    sem = asyncio.Semaphore(2)

    async def safe_fetch(order):
        async with sem:
            await asyncio.sleep(0.3)
            return await fetch_chat_and_check(order)

    results = await asyncio.gather(*[safe_fetch(o) for o in all_orders])
    hair_orders = [r for r in results if r is not None]

    to_sum = sum(float(o.get("totalPrice", 0)) for o in hair_orders)
    sales_total = len(hair_orders)

    # Маржа і кількість товарів з продуктів замовлень
    margin_sum = 0.0
    products_qty = 0
    for order in hair_orders:
        for product in order.get("products", []):
            price = float(product.get("price", 0))
            cost = float(product.get("costPrice", 0))
            qty = int(product.get("quantity", 1))
            margin_sum += (price - cost) * qty
            products_qty += qty

    # 3. Нові чати skin.one.hair за день (firstMessage = сьогодні)
    new_chats_all = await sitniks.get_all_chats(start_dt, end_dt, by_first_message=True)
    new_chats_hair = [c for c in new_chats_all if c.get("ownerName") == HAIR_OWNER_NAME]
    new_chats_count = len(new_chats_hair)

    # 4. Замовлення із діючих чатів = hair_orders, чиї chatId НЕ в нових чатах
    new_chat_ids = {c["id"] for c in new_chats_hair}
    orders_from_existing = [
        o for o in hair_orders
        if o.get("chatId") and o["chatId"] not in new_chat_ids
    ]
    existing_orders_count = len(orders_from_existing)

    leads = new_chats_count + existing_orders_count

    logger.info(
        f"Sitniks hair stats {target_date}: "
        f"ТО={to_sum:.2f} грн, маржа={margin_sum:.2f} грн, замовлень={sales_total}, "
        f"товарів={products_qty}, нових чатів={new_chats_count}, "
        f"замовлень з діючих={existing_orders_count}, заявок={leads}"
    )

    return {
        "to": round(to_sum, 2),
        "margin": round(margin_sum, 2),
        "leads": leads,
        "sales_total": sales_total,
        "sales_repeat": 0,  # поки що 0 — розділення по брендах в роботі
        "products_qty": products_qty,
    }


async def _get_fb_stats(fb: FacebookAdsClient, target_date: date) -> dict:
    """Повертає витрати, покази, кліки з Facebook Ads."""
    data = await fb.get_insights(target_date, target_date)
    logger.info(
        f"Facebook hair stats {target_date}: "
        f"spend={data['spend']}, impressions={data['impressions']}, "
        f"clicks={data['inline_link_clicks']}"
    )
    return {
        "fb_spend": data["spend"],
        "fb_impressions": data["impressions"],
        "fb_clicks": data["inline_link_clicks"],
    }


async def run_stats_for_date(
    target_date: date,
    fb_token: str,
    sheets: SheetsClient,
    sitniks: SitniksClient = None,
) -> dict:
    """
    Головна функція: збирає дані за target_date і записує в Google Sheets.
    Повертає зібрану статистику (dict).
    """
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
        logger.error(f"❌ Помилка запису статистики за {target_date}")

    return stats
