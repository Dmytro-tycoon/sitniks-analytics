# Контекст: аналітика замовлень з реклами

Стан на 28.09.2026.

## Що робить

Щодня о **08:30 Київ** cron-job `send_daily_ads_report`:

1. Тягне з Sitniks **усі замовлення за вчора**.
2. Розділяє на два потоки:
   - **Instagram Direct** (клієнти пишуть через Instagram Direct у Sitniks-чат)
   - **Сайт** (клієнти оформили на skin-one.com.ua — Sitniks додає `Сайт skin-one.com.ua` в `managerComment`)
3. Пише:
   - Telegram-звіт у групу «SKIN.ONE замовлення з реклами» — тільки по Instagram Direct
   - **Інстаграм** (gid 0, до 08.10.2026 — «Аркуш1») — суми по Instagram-рекламах
   - **Сайт** (gid 1552265568, до 08.10.2026 — «Аркуш3 Сайт») — суми по сайт-рекламах

Обидві таблиці в одному spreadsheet: `1vM6SIydglC0K0b-bZE5woq--2CK-BubXL8yfdnJqweQ` («Ефективність реклами 2»).

---

## Фільтр за статусом (обидва листи)

**День = календарна київська доба 00:00–24:00** (з 06.10.2026). ⚠️ Фільтр Sitniks
`createdAtFrom/To` ігнорує часовий пояс (доба стає 03:00–03:00) → для реклами
використовуємо `SitniksClient.get_orders_exact` (запас ±1 день + точне відсікання за createdAt);
Instagram з БД бере `order_date` ∈ {d-1, d} і залишає замовлення київської доби d.
Видалені в Sitniks замовлення (404) не рахуються.

**Не рахуємо** замовлення зі статусом у Sitniks: **«Новий», «Відмінено», «Не підтверджено», «Відмовилась», «Очікуємо оплату»** (останні два — з 06.10.2026)
(`src/analyzer/order_status.py:EXCLUDED_STATUS_TITLES`). Решта статусів
(«В роботі…», «ТТН сформовано», «Виконано» тощо) рахуються.
Повний список статусів — `GET /open-api/orders/statuses`.

Статус **і сума** (`totalPriceDiscount`) перевіряються **в Sitniks на момент запису в таблицю**
(з 05.10.2026: сума в `reported_ad_orders` — знімок на час звіту, а менеджер може змінити замовлення пізніше), тож при
перезаписі дня (бекфіл, 22:00 reattribute) скасовані пізніше замовлення
випадуть. Клітинки, що стали порожніми (в т.ч. «0»), `write_day` очищає.

---

## Instagram Direct (вкладка «Інстаграм»)

**Замовлення з сайту сюди НЕ входять** (з 28.09.2026) — вони лише в «Сайт».
Відсіюються і в `build_ad_report` (Telegram-звіт, `reported_ad_orders`), і при
записі в лист (старі рядки БД ще містять сайт-замовлення як «Без реклами (прямі)»).

Атрибуція: **найсвіжіший `adInfo` у Sitniks-чаті клієнта до дати замовлення**
(див. `src/analyzer/ad_analytics.py`).

Сума: `totalPriceDiscount`.
Стара атрибуція (>30 днів між останнім adInfo і замовленням) додається до
«Без реклами (прямі)».

Формат листа: A=`adTitle`, B=`Всього ₴` (формула), потім 12 міс × 32 колонки.

---

## Сайт (вкладка «Сайт»)

Модуль: `src/analyzer/site_orders.py`.

**Правила відбору замовлення:**

1. `managerComment` містить `"Сайт skin-one.com.ua"` (маркер) **або** канал продажу
   (`salesChannel.title`) = `"SKIN-ONE Assistant"` — Telegram-бот, через який замовляють
   відвідувачі сайту (з 07.10.2026). Даних про рекламу в бот-замовленнях немає →
   окремий рядок «Telegram-бот SKIN-ONE Assistant». З Instagram-вкладки вони виключаються.
2. Статус не «Новий» / «Відмінено» / «Не підтверджено» (див. «Фільтр за статусом»).

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
| **08:30** | **send_daily_ads_report** | Telegram-звіт + Інстаграм + Сайт |
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
    await write_daily_sums_to_sheet(target_date=d)          # Інстаграм
    await write_website_daily_sums_to_sheet(target_date=d)  # Сайт

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
- **Фільтр статусу**: пропускаємо «Новий», «Відмінено», «Не підтверджено» (з 28.09.2026 — для обох листів; до того лише «Новий» і лише для сайту).
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
