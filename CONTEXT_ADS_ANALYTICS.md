# Контекст: аналітика замовлень з реклами

Стан на 25.09.2026.

## Що робить

Щодня о **08:30 Київ** cron-job `send_daily_ads_report`:

1. Тягне з Sitniks **усі замовлення за вчора**.
2. Розділяє на два потоки:
   - **Instagram Direct** (клієнти пишуть через Instagram Direct у Sitniks-чат)
   - **Сайт** (клієнти оформили на skin-one.com.ua — Sitniks додає `Сайт skin-one.com.ua` в `managerComment`)
3. Пише:
   - Telegram-звіт у групу «SKIN.ONE замовлення з реклами» — тільки по Instagram Direct
   - **Аркуш1** — суми по Instagram-рекламах
   - **Аркуш3 Сайт** — суми по сайт-рекламах

Обидві таблиці в одному spreadsheet: `1vM6SIydglC0K0b-bZE5woq--2CK-BubXL8yfdnJqweQ` («Ефективність реклами 2»).

---

## Instagram Direct (Аркуш1)

Атрибуція: **найсвіжіший `adInfo` у Sitniks-чаті клієнта до дати замовлення**
(див. `src/analyzer/ad_analytics.py`).

Сума: `totalPriceDiscount`.
Стара атрибуція (>30 днів між останнім adInfo і замовленням) додається до
«Без реклами (прямі)».

Формат листа: A=`adTitle`, B=`Всього ₴` (формула), потім 12 міс × 32 колонки.

---

## Сайт (Аркуш3 Сайт)

Модуль: `src/analyzer/site_orders.py`.

**Правила відбору замовлення:**

1. `managerComment` містить `"Сайт skin-one.com.ua"` (маркер).
2. `status.title != "Новий"` — статус «Новий» означає що клієнт залишив заявку,
   але не сплатив (менеджер ще не оформив).

**Атрибуція:** з `managerComment` регексом `Реклама:\s*(.+?)\)` витягуємо
рядок типу `meta / skinone_catalog_2209 / 120260... / catalog (fbclid)`.
Якщо `Реклама:` відсутня — `Без реклами (прямі)`.

**Сума:** `totalPriceDiscount` — реальна сума з урахуванням знижки, включаючи
накладний платіж. Не з коментаря (там може бути «Разом X грн» до знижки).

**Дедуплікація:** по `order.id` — Sitniks-ID однозначний. Якщо клієнт подав
3 однакові заявки з сайту — у Sitniks буде 3 різні `order.id`, і всі три
рахуються (це реально 3 покупки, кожна оплачується окремо).

---

## Розклад cron

| Час (Київ) | Job | Що |
|---|---|---|
| 05:30 | daily_analysis_job | Аналіз діалогів менеджерів (Claude) |
| 05:30 | daily_hair_stats_job | Hair-бренд статистика → окремий Sheet |
| **08:30** | **send_daily_ads_report** | Telegram-звіт + Аркуш1 + Аркуш3 Сайт |
| 22:00 | reattribute_yesterday | Ретро-звірка Instagram-адсів (якщо Sitniks довантажив adInfo) |
| /30хв | scheduler_heartbeat | Просто щоб бачити чи планувальник живий |

---

## Ключові файли

- `src/telegram_bot/ads_bot.py` — cron entry-point `send_daily_ads_report`
- `src/analyzer/ad_analytics.py` — Instagram Direct логіка
- `src/analyzer/site_orders.py` — сайт-логіка (парсинг коментаря, фільтр статусу)
- `src/sheets/ads_sums.py` — Google Sheets writer (обидва листи через один клас з `sheet_name` параметром)
- `src/scheduler/jobs.py` — розклад cron
- `src/sitniks/client.py` — Sitniks API клієнт (retry, пагінація)

---

## Ручний бекфіл (за N днів)

```bash
cd ~/Documents/sitniks-analytics && source venv/bin/activate
python -W ignore -c "
import asyncio, sys
sys.path.insert(0, '.')
from datetime import date
from src.sheets.ads_sums import write_daily_sums_to_sheet, write_website_daily_sums_to_sheet

async def main():
    d = date(2026, 9, 25)
    await write_daily_sums_to_sheet(target_date=d)          # Аркуш1
    await write_website_daily_sums_to_sheet(target_date=d)  # Аркуш3 Сайт

asyncio.run(main())
"
```

---

## Комміти рефактору вересня 2026

- `919bf53` — refactor: pull website orders from Sitniks by comment
- `0ede267` — feat: skip site orders with status "Новий"
- `6148a03` — docs: refresh CONTEXT_ADS_ANALYTICS with new site-orders flow

Попередні коміти (парсер Telegram-повідомлень, sync з site-Supabase та звірку по телефону) прибрано.

---

## Історія рішень (для майбутніх сесій)

В процесі роботи над сайт-замовленнями спробували 3 підходи, залишили тільки останній:

### Підхід 1 (відкинутий): парсити Telegram-групу «SKIN.ONE заявки з сайту»
- Бот `@skinone_advertising_bot` доданий у групу як admin з `can_read_all_group_messages=true`
- Handler `handle_group_message` ловив повідомлення від «SKIN-ONE Assistant»
- Регекс витягав `order_id`, `Разом X грн`, `Реклама:`, phone, name
- Дані писались у таблицю `website_orders` (Supabase)
- **Мінуси:** тільки нові повідомлення (нема історії), не бачить, якщо клієнт скасував/змінив.
- **Артефакти:** таблиця `website_orders` існує в БД (не використовується); env var `WEBSITE_ORDERS_GROUP_ID=-5366972060` в Railway; файл `website_orders_parser.py` видалено.

### Підхід 2 (відкинутий): читати напряму БД сайту (`lnqydhqtpfohigcvdxrg`)
- Table `orders` містить `customer_name` з вкладеним «Реклама: XXX (fbclid)»
- Треба було SITE_SUPABASE_URL + SITE_SUPABASE_SERVICE_KEY
- **Проблема:** сума в БД сайту = заявлена клієнтом (напр. 1420), а не оплачена (1278 після знижки).
- **Артефакти:** ніякого коду не написав, тільки exploratory SQL.

### Підхід 3 (поточний): читати з Sitniks
- Sitniks вже має ці замовлення (сайт створює їх через API)
- В `managerComment` є маркер «Сайт skin-one.com.ua» і повний рядок «Реклама: XXX (fbclid)»
- `totalPriceDiscount` — реальна сума після знижок
- **Один API-запит на день** — все звідти
- Не потрібно нічого крім вже наявного `SitniksClient`

### Ключові рішення (з обговорення):
- **Сума** = `totalPriceDiscount` (варіант 1) — включаючи накладний платіж. НЕ payment.amount (передоплата). НЕ «Разом» з коментаря (сума до знижки).
- **Фільтр статусу**: пропускаємо `status.title == "Новий"` — це неоплачені заявки.
- **Дублі не проблема**: якщо клієнт замовив 3 рази — це 3 різні `order.id` в Sitniks і 3 різні оплати.
- Проміжна таблиця `website_orders` більше не потрібна — все на льоту.

---

## Приклади парсингу коментаря (для регресії)

```
Сайт skin-one.com.ua. звʼязок: Telegram; Нова Пошта, відділення: м. Красилів,
Хмельницький р-н, Хмельницька обл., Відділення №2 (до 30 кг): вул. Булаєнка, 8а;
оплата: оплата карткою на рахунок ФОП;
Реклама: instagram / profile / link_in_bio (fbclid).
Разом 1 420 грн
```
→ `ad_label = "instagram / profile / link_in_bio (fbclid)"`, `sum = 1278` (з totalPriceDiscount, не з "Разом 1 420")

```
❗️зібрано крім гель
❗️оригінали, 🎁маска biodance омолоджуюча
Сайт skin-one.com.ua. звʼязок: Telegram; ...; передоплата 200 грн, при отриманні 3 325 грн;
подарунок: маска Biodance омолоджуюча;
Реклама: meta / skinone_catalog_2209 / 120260678712650059 / catalog (fbclid).
Разом 3 525 грн
```
→ `ad_label = "meta / skinone_catalog_2209 / 120260678712650059 / catalog (fbclid)"`, `sum = 3525` (все, разом з накладним)
