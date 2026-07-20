# Сесія 15.07.2026 — NP-бот v2: деплой на Railway + переадресація + прибирання НП

Продовження сесії від 11.06.2026 (див. `SESSION_2026-06-11_NP_BOT.md`).

## Що зроблено цієї сесії

1. ✅ **Деплой NP-бота на Railway** (24/7, без залежності від локального мака)
2. ✅ **Виправлено баг з google-залежностями** в `requirements.txt` (без цього весь сервіс падав)
3. ✅ **`/redirect`** — переадресація ТТН на інше місто/відділення з вибором оплати
4. ✅ **Прибирання накладеного платежу для ТТН на складі** (не тільки для чернеток)

---

## Деплой на Railway

### Проблема, яку виявили побічно

При спробі задеплоїти NP-бот `serviceInstanceDeployV2` без `commitSha` тригерив redeploy **старого** commit (тому що це "redeploy current", не "deploy latest from git"). Правильний спосіб — передавати `commitSha` явно:

```graphql
mutation {
  serviceInstanceDeployV2(
    serviceId: "47310987-...",
    environmentId: "c52fafba-...",
    commitSha: "abcdef1"          # обов'язково!
  )
}
```

### Пропущений баг у попередньому релізі

`requirements.txt` не містив залежностей для Google Sheets (`google-api-python-client`, `google-auth`), хоча код у `src/sheets/client.py` їх використовував. Старий Railway-контейнер мав ці бібліотеки з попереднього середовища, тож не падав. **Мій перший redeploy зруйнував увесь сервіс** — довелось терміново додати залежності і задеплоїти. Урок: після зміни залежностей завжди перевіряти чи deploy piddає (не тільки status=SUCCESS, але й логи).

### Змінні у Railway (production)

Додав через GraphQL API (`variableUpsert`):
- `NP_BOT_TOKEN`
- `NP_OPERATOR_CHAT_IDS`
- `NP_ACCOUNTS`

`src/main.py` вже містив ініціалізацію NP-бота під `if settings.NP_BOT_TOKEN` — просто після появи змінної бот стартував автоматично.

---

## `/redirect` — переадресація ТТН

### Payload, знайдений через DevTools

```json
{
  "system": "PA 3.0",
  "modelName": "AdditionalServiceGeneral",
  "calledMethod": "save",
  "methodProperties": {
    "OrderType": "orderRedirecting",
    "IntDocNumber": "20451480238945",
    "Customer": "Sender",
    "Note": "Переадресація через бот",
    "OnlyGetPricing": 0,           // 1 для розрахунку, 0 для створення
    "PayerType": "Sender",         // або "Recipient"
    "PaymentMethod": "NonCash",    // або "Cash"
    "Recipient": "<Counterparty Ref>",
    "RecipientContactName": "Прізвище Ім'я",
    "RecipientPhone": "380...",
    "RecipientWarehouse": "<Warehouse Ref>",
    "Ref": "",
    "ServiceType": "WarehouseWarehouse"
  }
}
```

**Важливе:** тут `modelName` — `AdditionalServiceGeneral` (з `General`!), тоді як для `orderChangeEW` (зміна ПІБ/телефону/НП) — `AdditionalService` (без `General`). Різні моделі для різних типів заявок — легко переплутати.

### Flow у боті

```
/redirect <ттн>
  ↓ пошук у 3 кабінетах, показ поточної адреси
Введи назву нового міста
  ↓ Address.searchSettlements → 5-8 кнопок
Обери місто → введи номер відділення
  ↓ Address.getWarehouses з фільтром WarehouseId
Хто платить?
  [Відправник · безготівка]
  [Отримувач · готівка]
  ↓ AdditionalServiceGeneral.save з OnlyGetPricing=1 (розрахунок)
Підсумок з вартістю
  ↓
✅ Створити → OnlyGetPricing=0 → заявка створена
```

### Методи в `client.py`

- `search_settlements(query, limit)` → `Address.searchSettlements`
- `get_warehouses(city_ref, number)` → `Address.getWarehouses`
- `redirect_ttn(...)` → `AdditionalServiceGeneral.save` з OrderType=orderRedirecting

---

## Прибирання накладеного платежу (для прийнятих ТТН)

### Payload

```json
{
  "modelName": "AdditionalService",
  "OrderType": "orderChangeEW",         // той самий, що для зміни ПІБ
  "IntDocNumber": "20451482983048",
  "AfterpaymentOnGoodsCost": 0,         // ← ключове поле
  "BackwardDeliveryData": [],
  "PayerType": "Recipient",
  "PaymentMethod": "Cash"
}
```

### Оновлення в коді

У `request_change_after_accept()` прибрано NotImplementedError для `remove_cod=True`. Додано:
```python
if remove_cod:
    props["AfterpaymentOnGoodsCost"] = 0
    # BackwardDeliveryData: [] вже стоїть за замовчуванням
```

---

## Обмеження, які виявили

- `CheckPossibilityChangeEW → CanChangeBackwardDeliveryMoney: False` — якщо ТТН уже наближається до отримувача (напр. "Відправлення у м. Львів. Очікуйте повідомлення"), NP забороняє змінювати суму НП. Для тестування треба брати свіжі ТТН, недавно прийняті на склад.
- Заявки безкоштовні, але **скасувати їх не можна** — одразу йдуть в обробку.
- Зміна телефону через API опрацьовується швидко (хвилини), ПІБ — довше, іноді через СМС-підтвердження одержувачу.

---

## Комміти

| Hash | Опис |
|---|---|
| `56e2e39` | fix: add missing google deps for sheets client |
| `f42b678` | feat(np-bot): /redirect — переадресація ТТН |
| `dbb0bcb` | feat(np-bot): вибір оплати у /redirect |
| `2330328` | feat(np-bot): прибирання накладеного платежу для прийнятих ТТН |

---

## Фінальна функціональність бота

| Команда | Дія | Чернетка | На складі |
|---|---|---|---|
| `/registry` | Реєстр з чернеток + PDF-бланк | ✅ | — |
| `/edit → 📱 телефон` | Змінити телефон | ✅ | ✅ |
| `/edit → 👤 ПІБ` | Змінити ПІБ | ✅ | ✅ |
| `/edit → 💰 прибрати НП` | Прибрати накладений платіж | ✅ | ✅ |
| `/redirect` | Переадресація на інше відділення | — | ✅ |

---

## Робочі payload'и (шпаргалка)

### Зміна телефону (тільки телефон)
```
POST api.novaposhta.ua/v2.0/json/
{
  "modelName": "AdditionalServiceGeneral",  // (працює і як AdditionalService)
  "calledMethod": "save",
  "methodProperties": {
    "IntDocNumber": "...",
    "OrderType": "orderChangeEW",
    "RecipientPhone": "380..."
  }
}
```

### Зміна ПІБ (з телефоном або без)
Спершу створюємо нового Counterparty (PrivatePerson/Recipient) → отримуємо Ref → передаємо:
```
"modelName": "AdditionalService",
"methodProperties": {
  "IntDocNumber": "...",
  "OrderType": "orderChangeEW",
  "PayerType": "Recipient",
  "PaymentMethod": "Cash",
  "BackwardDeliveryData": [],
  "Recipient": "<new Counterparty Ref>",
  "RecipientContactName": "Прізвище Ім'я",
  "RecipientPhone": "..."
}
```

### Прибрати накладений платіж
```
"modelName": "AdditionalService",
"methodProperties": {
  "IntDocNumber": "...",
  "OrderType": "orderChangeEW",
  "AfterpaymentOnGoodsCost": 0,
  "BackwardDeliveryData": [],
  "PayerType": "Recipient",
  "PaymentMethod": "Cash"
}
```

### Переадресація
```
"modelName": "AdditionalServiceGeneral",   // з General!
"methodProperties": {
  "IntDocNumber": "...",
  "OrderType": "orderRedirecting",
  "Customer": "Sender",
  "OnlyGetPricing": 0,
  "PayerType": "Sender|Recipient",
  "PaymentMethod": "NonCash|Cash",
  "Recipient": "<existing Recipient Ref з ТТН>",
  "RecipientContactName": "...",
  "RecipientPhone": "...",
  "RecipientWarehouse": "<new Warehouse Ref>",
  "Ref": "",
  "ServiceType": "WarehouseWarehouse"
}
```

---

## Deploy на Railway (робочий рецепт)

```bash
# 1. Комітим і пушимо
git add ... && git commit -m "..." && git push origin main

# 2. Тригеримо deploy конкретного commit (без commitSha тригериться старий!)
python -c "
import urllib.request, json
from dotenv import dotenv_values
v = dotenv_values('.env')
H = {'Authorization': f'Bearer {v[\"RAILWAY_TOKEN\"]}',
     'Content-Type':'application/json', 'User-Agent': 'Mozilla/5.0'}
r = urllib.request.Request('https://backboard.railway.com/graphql/v2',
    data=json.dumps({'query':
      'mutation { serviceInstanceDeployV2('
      'serviceId: \"47310987-04a1-4e95-a974-a13fc599da33\", '
      'environmentId: \"c52fafba-7011-483a-93db-afceb9c15667\", '
      'commitSha: \"<SHORT_SHA>\") }'
    }).encode(), headers=H)
print(urllib.request.urlopen(r).read())
"

# 3. Перевіряємо статус
# Треба robotics-ключі: projectId=4750ab71-02cd-4b82-9134-a94e56267dd4
```

---

## TODO

| # | Що | Пріоритет |
|---|---|---|
| 1 | Перегенерувати NP_BOT_TOKEN через @BotFather /revoke | середній |
| 2 | 4-й кабінет НП — як з'явиться | низький |
| 3 | Логування дій оператора в Supabase для аудиту | низький |
| 4 | Можливість переадресації з зміною отримувача (не тільки відділення) | низький |

---

**Створено:** 15.07.2026
