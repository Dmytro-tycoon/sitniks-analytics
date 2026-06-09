# Sitniks Analytics — контекст сесії

> Документ описує стан системи аналітики менеджерів станом на 08.06.2026.
> Призначений для швидкого відновлення контексту при наступному запуску роботи.

---

## 1. Що це за проєкт

Автоматичний аналіз діалогів менеджерів-косметологів у Sitniks CRM:
**Sitniks → Claude AI → Supabase → Telegram звіти + real-time spam filter**.

**Бізнес:**
- Бренди `@skin.one.ua` (обличчя) і `@skin.one.hair` (волосся)
- 4 менеджери на 2 бренди (працюють з обома)
- Канал: Instagram Direct через Sitniks
- Експертний продаж косметики (підбір під тип шкіри/волосся)
- Робочий час: **08:00–23:00 Київ**

**4 менеджери:**
| Ім'я в Sitniks | Telegram username | chat_id |
|---|---|---|
| Єлизавета | @LChernyavskaya | 521207705 |
| Діана Кириченко 2 | @diana_kirichenko1 | 1344938702 |
| Вікторія Тумаш 2 | @Vik_tori_A77 | 7962771795 |
| Віка Палатай2 | @vic_tto_ria | 427263576 |

**Telegram групи:**
- Керівництво (group): `-5124563660`
- Дмитро (особисто): `448547265`
- Bot: `@managers_analytics_bot`

**Бренд-імена менеджерів:**
- "косметолог Анастасія" — для запитів по обличчю (skin.one.ua)
- "Катерина" — для запитів по волоссю (skin.one.hair)

Це навмисні бренд-псевдоніми, **не** помилки. Прописано в промпті.

---

## 2. Інфраструктура

| Сервіс | Призначення | Ключові ID |
|---|---|---|
| **Railway** | Хостинг 24/7 (worker + HTTP) | project `sitniks-analytics`, service `bot`, env `production`, **публічна URL** `https://bot-production-71cc6.up.railway.app` |
| **Supabase** | БД (Postgres) | project_id `igkemadfxebmcetxvhwx`, URL `https://igkemadfxebmcetxvhwx.supabase.co`, RLS увімкнено |
| **GitHub** | Код | https://github.com/Dmytro-tycoon/sitniks-analytics |
| **Anthropic Claude** | Аналіз | `claude-sonnet-4-6` (основний), `claude-haiku-4-5` (post-класифікація) |
| **Sitniks Open API** | Джерело даних | `https://crm.sitniks.com/open-api`, Bearer token |
| **Sitniks Webhooks** | Real-time події | "Повідомлення в чаті" → POST на наш `/webhook/sitniks` |

**Cron:** `daily_analysis_job` щодня о **06:00 Europe/Kiev**, `CronTrigger(hour=6, minute=0, timezone=KIEV_TZ)`.

---

## 3. Структура коду

```
src/
  config.py                 # завантаження env (з properties для lazy-eval)
  main.py                   # entrypoint: scheduler + telegram polling + web server
  webhook_server.py         # aiohttp сервер для Sitniks webhook
  sitniks/
    client.py               # HTTP client + retry на 429
                            # get_chat_messages пагінує (макс 50/стор), сортує за часом
                            # update_chat_tags для тегування
                            # get_orders, get_chats з firstMessage window
    parser.py               # format_dialog_for_claude (час → Київ) + to_kiev_str
  claude/
    client.py               # ClaudeAnalyzer single, retry на rate-limit
    batch.py                # ClaudeBatchAnalyzer (Batch API, -50%)
    prompts.py              # SYSTEM_PROMPT + ANALYSIS_PROMPT
  database/
    supabase_client.py      # CRUD: save_analysis, get_analyses_by_date,
                            #       save_feedback, get_analysis,
                            #       upsert_telegram_user, list_telegram_users
  analyzer/
    filter.py               # should_analyze() — фільтр коротких/порожніх
    spam_filter.py          # is_spam_profile() — евристика по name/nick
    metrics.py              # час відповіді, тривалість,
                            #       count_client_msgs_in_work_hours (Київ 08-23)
    pipeline.py             # analyze_period() — orchestration
  telegram_bot/
    bot.py                  # /today /yesterday /manager /whoami,
                            #       callback "fb:agree/disagree",
                            #       ForceReply для коментарів
    reports.py              # format_daily_report, format_manager_report,
                            #       format_review_item, select_review_items(top_good=2, top_bad=3)
  scheduler/
    jobs.py                 # daily_analysis_job + setup_scheduler

scripts/
  test_sitniks.py           # перевірка Sitniks API
  test_claude.py            # перевірка Claude single запит
  test_batch.py             # перевірка batch API
  one_off_analysis.py       # ручний запуск для дати
  run_now.py                # ручний run_now [date] — analyze + send
  classify_existing.py      # post-класифікація існуючих записів Haiku-моделлю
  get_chat_ids.py           # бот для збору telegram chat_id
```

---

## 4. Схема Supabase

### `dialog_analyses`
- `dialog_id` (TEXT, UNIQUE) — Sitniks chat ID
- `dialog_date` (DATE)
- `manager_name` (TEXT)
- `client_username`, `client_name` — Instagram nick і повне ім'я
- `has_order` (BOOLEAN) — **legacy**; реальні замовлення рахуються через `/orders`
- `messages_count`, `messages_from_manager`
- `client_msgs_in_work_hours` (INT) — кл. повідомлень у 08:00–23:00 Київ
- `avg_response_minutes`, `max_response_minutes`, `first_response_minutes`, `duration_minutes`
- `scores` (JSONB)
- `overall_score` (FLOAT)
- `alerts` (JSONB) — CR-1..CR-5, W-1..W-3 (CR-6 видалено)
- `strengths`, `improvements`, `summary`, `is_template_dialog`
- `dialog_quality` ('good'|'bad'|'neutral')
- `quality_reason` (TEXT)
- `user_confirmed` (BOOLEAN) — feedback від керівника
- `user_comment` (TEXT)
- `user_feedback_at` (TIMESTAMPTZ)

### `daily_reports`
- `report_date` (DATE, UNIQUE)
- `aggregated_data` (JSONB)
- `sent_to_telegram` (BOOLEAN)

### `criteria`
- single row, текст системних критеріїв

### `telegram_users`
- `chat_id` (BIGINT, PK)
- `username`, `first_name`, `last_name`
- `chat_type`, `chat_title`
- `first_seen_at`, `last_seen_at`

---

## 5. Метрики (поточна логіка)

**"Усього діалогів" = Нові чати + Чинні з замовленням** (як у Sitniks dashboard):
- **Нові чати** = `firstMessageStartDate/EndDate` window
- **Чинні з замовленням** = chatId з orders за день, які НЕ потрапили в нові

**Реальна кількість замовлень** з `/orders` Sitniks API через
`responsible.user.fullname` групування.

Прив'язка order ↔ chat — через `chatId` поле в `/orders`.

---

## 6. Економія Claude

Стартова вартість була ~$270/міс. Зараз ~$60-70/міс через:

1. **Anthropic Batch API** — `-50%` на input + output
2. **Фільтр коротких** (`src/analyzer/filter.py`):
   - < 2 повідомлень → skip
   - менеджер не відповів → skip + окрема секція у звіті
   - клієнт не відповів → skip (одностороннє привітання)
3. **Скорочений JSON output** — `max_tokens=1500`
4. **Prompt caching** на SYSTEM_PROMPT (`cache_control: ephemeral`)

---

## 7. Anthropic Tier

**Tier 1** (8000 output tokens/хв, 50 RPM) — поки на цьому.
Рекомендовано поповнити баланс до **$40** для авто-апгрейду на Tier 2.

---

## 8. Telegram-звіт: формат

**Щоранку о 06:00 Київ** в групу "Керівництво":

1. Загальний звіт (один message):
   - Загальні показники + рейтинг менеджерів + критичні алерти
   - 🔇 "Менеджер не відповів" — тільки де клієнт писав у робочий час 08:00–23:00 Київ (нічна активність виключається)
2. **2 хороших + 3 поганих** приклади — кожен окремим повідомленням з inline-кнопками:
   - **✅ Згоден** → `user_confirmed=true`
   - **❌ Не згоден** → `user_confirmed=false` + ForceReply просить коментар
   - Коментар парситься з reply через regex `🆔 ([0-9a-f]{24})` у самому ForceReply text

**Особисті звіти менеджерам:** наразі через **TELEGRAM_SHADOW_CHAT_ID** (= 448547265 Dmitriy) — всі звіти йдуть в одне місце, з префіксом `📋 Звіт для {ім'я}`. Менеджерам напряму НЕ розсилаємо. Щоб увімкнути — видалити змінну `TELEGRAM_SHADOW_CHAT_ID` у Railway.

**Лінки на чати в Sitniks:** формат `https://web.sitniks.com/2341/chats/dialog/{dialog_id}`.

---

## 9. Калібрування Claude — поточний стан

Промпт пройшов **3 ітерації** на основі feedback керівника. Поточні правила:

### Алгоритм класифікації (3 кроки):

**КРОК 1.** Опт / постачання / косметолог-перепродавець / B2B → завжди `neutral`.

**КРОК 2.** Замовлення є?
- overall ≥ 4 і немає критичних помилок (експертність ≥ 3, тон ≥ 5) → `good`
- overall < 3 АБО грубість АБО експертність ≤ 2 → `bad`
- інакше → `neutral`

**КРОК 3.** Без замовлення:
- `bad` ТІЛЬКИ при явній помилці менеджера (грубість/ігнор/дезінформація/відштовхнув)
- усе інше → `neutral` (клієнт мовчить, конкретний запит, нема товару, нічна активність)

### Алерти:
- **CR-1..CR-5**: грубість, ігнор >1год робочого часу, неправдива інформація, знижка без узгодження, конфлікт
- **CR-6 видалено** (Claude вгадував без даних; реальні суми рахуємо з /orders)
- **W-1..W-3**: загальна оцінка <5, втрата готового клієнта, низька експертність

---

## 10. Виявлені інженерні баги і виправлення

| Баг | Виправлення |
|---|---|
| Sitniks 429 rate-limit при daily-job | Retry з exp backoff в `SitniksClient._get_with_retry()`, concurrency=2, sleep між запитами |
| Anthropic rate-limit | Retry з exp backoff в `ClaudeAnalyzer.analyze_dialog()` |
| `daily_analysis_job` запускався в UTC замість Києва | `CronTrigger(timezone=KIEV_TZ)` явно |
| Telegram polling conflict при redeploy | Залежить від Railway grace shutdown |
| `print()` буферизовано в Railway | `python -u` (unbuffered) у `startCommand` |
| RLS попередження від Supabase | Увімкнено RLS на всіх таблицях (`service_role` bypass) |
| Sitniks повертає час в UTC, Claude приймає як локальний | `to_kiev_str()` в `src/sitniks/parser.py` + явне `(Київ)` |
| `get_chat_messages` повертав тільки 10 з 75+ повідомлень | Додано пагінацію (limit=50, skip)+ сортування за часом |
| "Менеджер не відповів" включав порожні чати | Фільтр `client_msgs_in_work_hours > 0` (Київ 08-23) |
| `CR-6 >5000 грн алерт` Claude вгадував | Прибрано з промпта |

---

## 11. Real-time spam-фільтр (08.06.2026)

**Webhook URL:** `https://bot-production-71cc6.up.railway.app/webhook/sitniks`

У Sitniks UI створено вебхук:
- **Подія:** "Повідомлення в чаті"
- **Джерело:** Instagram (або всі)

### Як працює:
1. Клієнт пише → Sitniks шле webhook → наш HTTP сервер (`src/webhook_server.py`)
2. За ~1-3 сек бот:
   - Тягне `get_chat(chatId)` → отримує `userName`, `userNickName`
   - Запускає `is_spam_profile(name, nick)` — евристика по патернах
   - Якщо спам → `update_chat_tags(chat_id, [..., "🚫 SPAM"])`
   - Шле в Telegram (Дмитру) сповіщення з лінком на чат — **один раз на чат**
3. Дмитро в Sitniks UI вручну перепризначає "Відповідальний → Дмитро" (~5 сек)

### Чому не повна автоматика
`PUT /chats/{id}` через Open API дозволяє оновлювати **тільки `tags`**, поля `assignedManagerId` нема. Подано запит у Sitniks support на розширення Open API.

### Спам-патерни (`src/analyzer/spam_filter.py`):
- **У імені:** `support`, `business`, `chat ai`, `support ai`, `assistant`, `helpdesk`, `customer service/care`, `crypto/bitcoin/btc/eth/usdt/invest/forex/trader/trading`, `official ... support/page`, `verified`, `claim/prize/winner/gift/reward`
- **У ніку:** суфікси `_love\d*`, `_official\d*`, `_support\d*`, `_help\d*`, `_bot\d*`; префікси `chat_`, `bot_`, `support_`, `ai_`

### Дедуплікація:
- `_NOTIFIED_SPAM_CHATS` (in-memory) — не дублює Telegram-сповіщення при кожному повідомленні в тому ж чаті

---

## 12. Що в TODO / на майбутнє

| # | Що | Пріоритет |
|---|---|---|
| 1 | Поповнити Anthropic баланс на $40 → Tier 2 | високий |
| 2 | Чекати відповідь Sitniks support на запит про `assignedManagerId` у Open API | високий |
| 3 | Зібрати ще 20-30 feedback від керівника → переаналіз v4 промпта | середній |
| 4 | Через 30-50 підтверджених еталонів — додати few-shot examples | середній |
| 5 | Точкові спам-патерни (false positives → exception list) | середній |
| 6 | Налаштувати auto-deploy GitHub→Railway | низький |
| 7 | Команда `/review` для пакетного перегляду непідтверджених good/bad | низький |
| 8 | Тижневі/місячні звіти з графіками | низький |

---

## 13. Корисні команди

```bash
# Локальний запуск (для дебагу)
cd ~/Documents/sitniks-analytics
source venv/bin/activate
python -m src.main

# Разовий аналіз за конкретну дату
python scripts/run_now.py 2026-06-03

# Перекласифікувати існуючі записи (Haiku)
python scripts/classify_existing.py 2026-06-03

# Тестовий webhook payload
curl -X POST https://bot-production-71cc6.up.railway.app/webhook/sitniks \
  -H "Content-Type: application/json" \
  -d '{"chat":{"id":"6a216110a96a9df8bd341f0f"},"message":{}}'

# Railway redeploy (через GraphQL з токеном)
curl -s -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -d '{"query":"mutation { serviceInstanceDeployV2(serviceId:\"47310987-04a1-4e95-a974-a13fc599da33\", environmentId:\"c52fafba-7011-483a-93db-afceb9c15667\") }"}'
```

---

## 14. Ключі і доступи (всі в локальному `.env` + Railway Variables)

| Змінна | Значення / Місце |
|---|---|
| `SITNIKS_API_KEY` | див. локальний `.env` |
| `SITNIKS_API_URL` | `https://crm.sitniks.com/open-api` |
| `ANTHROPIC_API_KEY` | див. локальний `.env` |
| `TELEGRAM_BOT_TOKEN` | див. локальний `.env` |
| `TELEGRAM_LEADERSHIP_CHAT_ID` | `-5124563660` |
| `TELEGRAM_MANAGERS` | JSON 4 менеджерів |
| `TELEGRAM_SHADOW_CHAT_ID` | `448547265` (Dmitriy) — поки активно |
| `SUPABASE_URL` | `https://igkemadfxebmcetxvhwx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | див. локальний `.env` |
| `ANALYSIS_TIMEZONE` | `Europe/Kiev` |
| `DAILY_REPORT_TIME` | `09:00` (legacy, не використовується) |
| `ADS_BOT_TOKEN` | окремий бот для аналізу реклами (новий, в розробці) |
| `ADS_REPORT_CHAT_ID` | `448547265` (Dmitriy) |
| `PORT` | `8080` (Railway authoritative) |

Railway Token, GitHub PAT, Anthropic key, Sitniks key, Bot tokens — у локальному `.env` (НЕ комітити!).

---

## 15. Контактні точки

- Telegram бот аналітики: `@managers_analytics_bot`
- Webhook URL Sitniks: `https://bot-production-71cc6.up.railway.app/webhook/sitniks`
- Health check: `https://bot-production-71cc6.up.railway.app/`
- Email Supabase алерти: `tycoon.dmitriy1@gmail.com`
- GitHub owner: `Dmytro-tycoon`
- Railway team: `dmytro-tycoon's Projects`

---

**Останнє оновлення:** 08.06.2026 — додано real-time spam-фільтр через Sitniks webhook + HTTP-сервер на Railway.
