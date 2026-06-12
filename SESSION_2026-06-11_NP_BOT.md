# Сесія 11.06.2026 — Бот для роботи з кабінетами Нової Пошти

## Мета

Створити окремий Telegram-бот, через який оператор може:
- Створювати реєстр відправлень з чернеток (без ручного вводу ТТН)
- Редагувати ТТН: телефон, ПІБ отримувача, прибирати накладений платіж
- (заплановано) Переадресовувати відправлення

Бот: **@skinone_np_bot** ("Skin.One Нова Пошта")

---

## Інфраструктура

| Параметр | Значення |
|---|---|
| Bot username | `@skinone_np_bot` |
| Bot токен | `NP_BOT_TOKEN` (env, локальний `.env`) |
| Хостинг | поки тільки локально (Railway-деплой — TODO) |
| Запуск | `python -m scripts.run_np_bot` (standalone, не через `src.main`) |
| Оператори (chat_ids) | `448547265` (Дмитро), `605470967` (Наташа) |
| Файл логів | `/tmp/np_bot.log` |

### Кабінети Нової Пошти

3 ФОП-кабінети (буде 4-й):

| Назва | API-ключ (Бізнес-кабінет) |
|---|---|
| ФОП Ємець Д.Л. | в локальному `.env` (NP_ACCOUNTS[0]) |
| ФОП Ємець А.М. | NP_ACCOUNTS[1] |
| ФОП Ємець А.Л. | NP_ACCOUNTS[2] |

⚠️ Потрібен саме ключ **"Бізнес-кабінет"** (не "Мобільний додаток") — лише він має доступ до ScanSheet, повного списку ТТН і AdditionalService.

---

## Структура коду

```
src/
  novaposhta/
    client.py             # NP API client (всі методи нижче)
  telegram_bot/
    np_bot.py             # бот: /start /registry /edit
  config.py               # додано NP_BOT_TOKEN, NP_OPERATOR_CHAT_IDS, NP_ACCOUNTS

scripts/
  run_np_bot.py           # standalone-запуск тільки NP-бота
```

### `src/novaposhta/client.py`

| Метод | Призначення |
|---|---|
| `get_drafts(days_back=7)` | список ТТН-чернеток у кабінеті (StateId=1, без ScanSheet) |
| `create_registry(doc_refs)` | створює реєстр через `ScanSheet.insertDocuments` (без Ref = новий) |
| `download_registry_pdf(scan_sheet_ref)` | завантажує офіційний PDF-бланк зі штрихкодом |
| `find_document(ttn_number)` | шукає ТТН за номером (за останні 60 днів) |
| `check_possibility_change(ttn_number)` | `AdditionalService.CheckPossibilityChangeEW` |
| `update_draft(doc_raw, new_phone, new_name, remove_cod)` | для чернеток — `InternetDocument.update` |
| `request_change_after_accept(...)` | для прийнятих ТТН — `AdditionalService.save` з `OrderType=orderChangeEW` |

### `src/telegram_bot/np_bot.py`

Команди:
- `/start` — інструкція
- `/registry` — створити реєстр з чернеток (FSM: `RegistryFlow`)
- `/edit <номер ТТН>` — редагувати ТТН (FSM: `EditFlow`)

Бот сам визначає чи ТТН чернетка чи на складі:
- 🟢 Чернетка → зміни через `InternetDocument.update`
- 🟠 На складі → зміни через `AdditionalService.save` (заявка)

---

## Поточний функціонал

### 1. `/registry` — створення реєстру

```
/registry
  ↓
[якщо кілька кабінетів] обираєш кабінет
  ↓
Бот тягне всі чернетки (StateId=1) за 7 днів
  ↓
Показує список (макс 30 ТТН з підказкою)
  ↓
✅ Створити реєстр
  ↓
ScanSheet.insertDocuments (Date у форматі DD.MM.YYYY!)
  ↓
Повідомлення з № реєстру + PDF-бланк зі штрихкодом
```

**Інсайти про NP API:**
- `ScanSheet.insertDocuments` без `Ref` створює новий реєстр (метод `ScanSheet.save` не існує)
- Date вимагає формат `DD.MM.YYYY` (не ISO)
- PDF-бланк: `https://my.novaposhta.ua/scanSheet/printScanSheet/refs[]/{ref}/type/pdf/apiKey/{key}` (URL `/orders/printScanSheet/orders[]/...` повертає 404)

### 2. `/edit <ttn>` — редагування ТТН

```
/edit 20451459116069
  ↓
Бот шукає ТТН в усіх кабінетах за 60 днів
  ↓
📦 ТТН #...
Кабінет: ...
Статус: ... | Тип зміни: 🟢/🟠
Отримувач, телефон, адреса, НП
  ↓
[📱 Телефон] [👤 ПІБ] [💰 Прибрати НП] [❌ Закрити]
  ↓
Відповідно до вибору — FSM запитує новий телефон/ПІБ/підтвердження
  ↓
Виконання та повідомлення
```

**Що працює:**
- 📱 Телефон — для чернеток і ТТН на складі ✅
- 👤 ПІБ — для чернеток і ТТН на складі ✅
- 💰 Прибрати НП — тільки для чернеток ✅

**Що в розробці:**
- Прибрати НП для ТТН на складі (потрібна реальна ТТН з НП для DevTools-аналізу)

---

## Знайдені/виправлені інженерні баги

| Проблема | Розв'язання |
|---|---|
| `ScanSheet.save` not found | Прибрати step "create empty sheet" — `insertDocuments` без `Ref` сам створює реєстр |
| "Невірний формат дати" в insertDocuments | Дата `DD.MM.YYYY` замість `YYYY-MM-DD` |
| PDF реєстру 404 (`my.novaposhta.ua/orders/printScanSheet/orders[]/...`) | Правильний URL: `my.novaposhta.ua/scanSheet/printScanSheet/refs[]/{ref}/type/pdf/apiKey/{key}` |
| Чернетки не знаходились (фільтр по `ScanSheetNumber` пустому) | Додати ще `StateId == "1"` як критерій draft |
| `RecipientCity` показувався як UUID | Замінити на `CityRecipientDescription` |
| `OrderType: cargoChangeOfOwnership` is invalid | Правильний — `orderChangeEW` (з малої) |
| Зміна ПІБ через API: "No data changes" з полями FirstName/LastName/Recipient (Ref) | **Через DevTools з'ясовано:** modelName має бути `AdditionalService` (не `AdditionalServiceGeneral`), і ПІБ передається одним рядком як `RecipientContactName` + потрібен Counterparty Ref + `PayerType` + `PaymentMethod` + `BackwardDeliveryData: []` |
| Webhook сервер падав через зайнятий 8000 (дублі процесів) | Зробив окремий `scripts/run_np_bot.py` (без webhook/основних ботів) |
| TelegramConflictError локально | Основний+ads боти крутяться на Railway паралельно. Локальний запуск тільки NP бота через standalone-скрипт |

---

## Точний payload зміни даних ТТН (після прийому на склад)

Це той, що шле NP UI кабінету при ручному створенні заявки:

```json
{
  "system": "PA 3.0",
  "modelName": "AdditionalService",
  "calledMethod": "save",
  "methodProperties": {
    "IntDocNumber": "20451460531556",
    "OrderType": "orderChangeEW",
    "PayerType": "Recipient",
    "PaymentMethod": "Cash",
    "BackwardDeliveryData": [],
    "Recipient": "<UUID нового Counterparty (PrivatePerson, Recipient)>",
    "RecipientContactName": "Прізвище Ім'я По-батькові",
    "RecipientPhone": "380XXXXXXXXX"
  }
}
```

Створення нового `Counterparty` — через `CounterpartyGeneral.save` з:
- `CounterpartyType: "PrivatePerson"`
- `CounterpartyProperty: "Recipient"`
- `FirstName`, `LastName`, `MiddleName`, `Phone`

---

## Важливі факти про NP API

- Заявки на зміну даних — **безкоштовні** (не 25-50 грн, як писав раніше)
- Скасувати створену заявку **не можна** — одразу йде в обробку
- Зміна можлива через API лише за умов `CheckPossibilityChangeEW` → `CanChangeRecipient: true` тощо
- Зміна тільки телефону спрацьовує швидко (хвилини), ПІБ — повільніше
- Поле `ScanSheetNumber` пусте = ТТН не в реєстрі. `StateId=1` = ще не прийнята на склад

---

## Що НЕ використано (помилкові гіпотези)

- `ScanSheet.save` → не існує як метод
- `AdditionalServiceGeneral` модель → правильна `AdditionalService`
- `OrderType: cargoChangeOfOwnership` → invalid (правильний `orderChangeEW`)
- `ContactPersonRecipient` як Ref → не потрібен у payload
- `FirstName/LastName/MiddleName` як окремі поля → не приймаються в `AdditionalService.save`

---

## TODO

| # | Що | Пріоритет |
|---|---|---|
| 1 | Деплой на Railway (додати NP_* змінні + redeploy) | високий |
| 2 | **Перегенерувати NP_BOT_TOKEN** через `@BotFather /revoke` (старий світився у відкритому чаті) | високий |
| 3 | Закомітити все в git (зараз тільки локально) | високий |
| 4 | Команда `/redirect <ttn>` — переадресація (потребує DevTools-аналізу) | середній |
| 5 | Прибирання накладеного платежу для прийнятих ТТН (потребує DevTools-аналізу на ТТН з НП) | середній |
| 6 | 4-й кабінет НП (коли з'явиться) | низький |
| 7 | Логування дій оператора в Supabase для аудиту | низький |

---

## Запуск/перезапуск локально

```bash
# Запуск
cd ~/Documents/sitniks-analytics
source venv/bin/activate
nohup python -u -m scripts.run_np_bot > /tmp/np_bot.log 2>&1 &

# Перевірка статусу
pgrep -fa "run_np_bot"
tail -20 /tmp/np_bot.log

# Зупинити
pkill -9 -f "run_np_bot"
```

---

## Корисні факти для дебагу

- Лог Telegram-конфліктів (`TelegramConflictError`) при паралельному `src.main` локально — нормально (Railway тримає основний/ads бот). NP-бот окремий, не конфліктує.
- При помилці "Please wait" від NP API — rate-limit, треба паузу ~10-30 сек між запитами
- `CheckPossibilityChangeEW` повертає поточний стан ТТН разом з прапорцями можливостей — корисно для відображення в `/edit`

---

**Створено:** 11.06.2026
