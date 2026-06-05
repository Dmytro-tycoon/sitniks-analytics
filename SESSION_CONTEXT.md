# Sitniks Analytics — контекст сесії

> Документ описує стан системи аналітики менеджерів станом на 04.06.2026.
> Призначений для швидкого відновлення контексту при наступному запуску роботи.

---

## 1. Що це за проєкт

Автоматичний аналіз діалогів менеджерів-косметологів у Sitniks CRM:
**Sitniks → Claude AI → Supabase → Telegram звіти**.

**Клієнт/бізнес:**
- Бренди `@skin.one.ua` (обличчя) і `@skin.one.hair` (волосся)
- 4 менеджери на 2 бренди (працюють з обома)
- Канал: Instagram Direct через Sitniks
- Експертний продаж косметики (підбір під тип шкіри/волосся)

**4 менеджери:**
| Ім'я в Sitniks | Telegram username | Telegram chat_id |
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
- "косметолог Анастасія" — для запитів по обличчю
- "Катерина" — для запитів по волоссю

Це навмисні бренд-псевдоніми, **не** помилки. Прописано в промпті.

---

## 2. Інфраструктура

| Сервіс | Призначення | Ключові ID |
|---|---|---|
| **Railway** | Хостинг 24/7 | project `sitniks-analytics` (4750ab71-02cd-4b82-9134-a94e56267dd4), service `bot` (47310987-04a1-4e95-a974-a13fc599da33), env `production` (c52fafba-7011-483a-93db-afceb9c15667) |
| **Supabase** | БД (Postgres) | project_id `igkemadfxebmcetxvhwx`, URL `https://igkemadfxebmcetxvhwx.supabase.co`, RLS увімкнено |
| **GitHub** | Код | https://github.com/Dmytro-tycoon/sitniks-analytics (public, поки немає auto-deploy в Railway — деплою через GraphQL mutation) |
| **Anthropic Claude** | Аналіз | model `claude-sonnet-4-6` для основного аналізу, `claude-haiku-4-5` для post-класифікації існуючих даних |
| **Sitniks Open API** | Джерело даних | `https://crm.sitniks.com/open-api`, Bearer token |

**Cron:** `daily_analysis_job` щодня о **06:00 Europe/Kiev**. Проблема з timezone виправлена — `CronTrigger(hour=6, minute=0, timezone=KIEV_TZ)`.

---

## 3. Структура коду

```
src/
  config.py                 # завантаження env (з properties для lazy-eval)
  main.py                   # entrypoint: scheduler + telegram polling
  sitniks/
    client.py               # HTTP client + retry на 429
    parser.py               # format_dialog_for_claude + to_kiev_str
  claude/
    client.py               # ClaudeAnalyzer (single), retry на rate-limit
    batch.py                # ClaudeBatchAnalyzer (Anthropic Batch API, -50%)
    prompts.py              # SYSTEM_PROMPT + ANALYSIS_PROMPT
  database/
    supabase_client.py      # CRUD: save_analysis, get_analyses_by_date,
                            #       save_feedback, get_analysis,
                            #       upsert_telegram_user, list_telegram_users
  analyzer/
    filter.py               # should_analyze() — фільтр коротких/порожніх
    metrics.py              # час відповіді, тривалість
    pipeline.py             # analyze_period() — orchestration
  telegram_bot/
    bot.py                  # handlers /today /yesterday /manager /whoami,
                            #          callback "fb:agree/disagree",
                            #          ForceReply для коментарів
    reports.py              # format_daily_report, format_manager_report,
                            #          format_review_item, select_review_items
  scheduler/
    jobs.py                 # daily_analysis_job + setup_scheduler

scripts/
  test_sitniks.py           # перевірка Sitniks API
  test_claude.py            # перевірка Claude single запит
  test_batch.py             # перевірка batch API
  one_off_analysis.py       # ручний запуск для дати
  run_now.py                # ручний run_now [date] — analyze + send
  bulk_analysis.py          # масовий тестовий аналіз
  classify_existing.py      # post-класифікація існуючих записів Haiku-моделлю
  get_chat_ids.py           # бот для збору telegram chat_id
```

---

## 4. Схема Supabase

### `dialog_analyses`
- `dialog_id` (TEXT, PK з UNIQUE) — Sitniks chat ID, формат `6a2155f1...`
- `dialog_date` (DATE)
- `manager_name` (TEXT)
- `client_username`, `client_name` — Instagram nick і повне ім'я
- `has_order` (BOOLEAN) — **legacy, не використовується**; реальна кількість замовлень рахується через `/orders` API
- `messages_count`, `messages_from_manager`
- `avg_response_minutes`, `max_response_minutes`, `first_response_minutes`, `duration_minutes`
- `scores` (JSONB) — оцінки по 7 критеріях
- `overall_score` (FLOAT)
- `alerts` (JSONB)
- `strengths`, `improvements` (JSONB)
- `summary` (TEXT)
- `is_template_dialog` (BOOLEAN)
- `dialog_quality` ('good'|'bad'|'neutral')
- `quality_reason` (TEXT)
- **`user_confirmed`** (BOOLEAN) — feedback від керівника
- **`user_comment`** (TEXT) — коментар при ❌
- **`user_feedback_at`** (TIMESTAMPTZ)

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
- **Нові чати** = чати з `firstMessageStartDate/EndDate` window (Sitniks параметр)
- **Чинні з замовленням** = chatId з orders за день, які НЕ потрапили в нові

**Реальна кількість замовлень** береться з `/orders` Sitniks API через
`responsible.user.fullname` групування (НЕ з `has_order` чату).

Прив'язка order ↔ chat — через `chatId` поле в `/orders` (присутнє у списку і деталі).

---

## 6. Економія Claude

Стартова вартість була ~$270/міс. Зараз ~$60-70/міс через комбінацію:

1. **Anthropic Batch API** — `-50%` на input + output (~5-15 хв обробки замість real-time)
2. **Фільтр коротких** (`src/analyzer/filter.py`):
   - < 2 повідомлень → skip
   - менеджер не відповів → skip + окрема секція у звіті
   - клієнт не відповів → skip (одностороннє привітання, не аналізуємо)
3. **Скорочений JSON output** — `max_tokens=1500`, лаконічний формат
4. **Prompt caching** на SYSTEM_PROMPT через `cache_control: ephemeral`

---

## 7. Anthropic Tier

**Tier 1** (8000 output tokens/хв, 50 RPM) — поки на цьому.
Рекомендовано поповнити баланс до **$40** для автоматичного апгрейду на Tier 2 (16k tokens/min, 1000 RPM). Це покриє ~30 днів роботи з запасом.

---

## 8. Telegram-звіт: формат

**Щоранку о 06:00 Київ** в групу "Керівництво":

1. Загальний звіт (один message):
   - Загальні показники + рейтинг менеджерів + критичні алерти + секції 🔇 "Менеджер не відповів"
2. Окремі повідомлення **🏆 Хороші приклади** і **💔 Для розбору** — з inline-кнопками:
   - **✅ Згоден** → записує `user_confirmed=true`
   - **❌ Не згоден** → записує `user_confirmed=false` + ForceReply просить коментар
   - Коментар парситься з reply через regex `🆔 ([0-9a-f]{24})` у самому ForceReply text

**Особисті звіти менеджерам:** наразі через **TELEGRAM_SHADOW_CHAT_ID** (= 448547265 Dmitriy) — всі звіти йдуть в одне місце, з префіксом `📋 Звіт для {ім'я}`. Менеджерам напряму поки **НЕ розсилаємо**. Щоб увімкнути — видалити змінну `TELEGRAM_SHADOW_CHAT_ID` у Railway.

**Лінки на чати в Sitniks:** формат `https://web.sitniks.com/2341/chats/dialog/{dialog_id}` — відкривають конкретний чат.

---

## 9. Калібрування Claude — поточний стан

Промпт пройшов **3 ітерації** на основі feedback керівника:

### v1 (стартовий)
- Дуже суворий, давав 67 з 80 діалогів `bad`, 0 `good`

### v2 (після перших feedback)
- Додані правила про "Анастасія/Катерина", замовлення = good, клієнт не відповів = neutral
- Результат: 7 good, 6 bad, 67 neutral
- Збіг з думкою керівника: 7/13 = 54%

### v3 (поточний, поки тільки на старих даних класифікатор Haiku)
- Структуровано як 3-крокова перевірка
- Крок 1: опт/B2B/постачання → завжди neutral
- Крок 2: замовлення є → дивимось якість (overall>=4 + експертність>=3 + тон>=5 = good; критичні провали = bad; інакше = neutral)
- Крок 3: без замовлення → bad тільки при явних помилках менеджера; усе інше = neutral
- Результат: 7 good, 6 bad, 67 neutral (Haiku post-classifier для 03.06)
- Збіг: 8/13 = 62%

### Поточні правила в промпті (`src/claude/prompts.py`):

**НЕ позначати bad:**
1. Клієнт перестав відповідати після коректної відповіді менеджера
2. Оптовий запит / постачальник / косметолог-перепродавець
3. Товару немає в наявності, альтернатива запропонована
4. Конкретний запит на товар X — менеджер відповів, без насильного допродажу
5. Замовлення з overall>=4 — це good (навіть з дрібними недоліками)
6. Швидке привітання + тиша клієнта

**bad при замовленні** — тільки якщо overall<3 АБО експертність<=2 АБО грубість.

---

## 10. Виявлені інженерні баги і виправлення

| Баг | Виправлення |
|---|---|
| Sitniks 429 rate-limit при daily-job | Retry з exp backoff в `SitniksClient._get_with_retry()`, concurrency=2, sleep між запитами |
| Anthropic rate-limit (Tier 1) | Retry з exp backoff в `ClaudeAnalyzer.analyze_dialog()` |
| `daily_analysis_job` запускався в UTC замість Києва | `CronTrigger(timezone=KIEV_TZ)` явно |
| Telegram polling conflict при redeploy | Залежить від Railway grace shutdown; вирішується `deploymentStop` + повторний deploy |
| `print()` буферизовано в Railway | `python -u` (unbuffered) у `startCommand` |
| RLS попередження від Supabase | Увімкнено RLS на всіх таблицях (`service_role` bypass) |
| Sitniks повертає час в UTC, Claude приймає як локальний | `to_kiev_str()` в `src/sitniks/parser.py` + явне `(Київ)` в ANALYSIS_PROMPT + "Робочий час: 09:00-22:00 Київ" |

---

## 11. Останнє виправлення (04.06)

**Алерт CR-2 про "2 год затримки"** виявився коректним — менеджер дійсно довго відповідав. Але часи в діалозі передавалися в UTC, а Claude інтерпретував їх як Київ → плутанина у розпізнаванні "робочого часу".

**Що зроблено:**
- `src/sitniks/parser.py`: додано `to_kiev_str(iso_ts)` — конвертує UTC у Київ
- `format_dialog_for_claude` — всі часи в діалозі тепер у Київському часі
- `src/analyzer/pipeline.py`: `started_at` тепер у форматі `"2026-06-04 14:27 (Київ)"`
- `src/claude/prompts.py`: додано префікс у ANALYSIS_PROMPT:
  > ⏰ Усі мітки часу в діалозі — у Київському часі (Europe/Kiev).
  > Робочий час менеджерів: 09:00–22:00 Київ.

---

## 12. Що в TODO / на майбутнє

| # | Що | Пріоритет |
|---|---|---|
| 1 | Поповнити Anthropic баланс на $40 → Tier 2 | високий |
| 2 | Зібрати ще 20-30 feedback від керівника → переаналіз v4 промпта | середній |
| 3 | Через 30-50 підтверджених еталонів — додати few-shot examples в системний промпт | середній |
| 4 | Налаштувати auto-deploy GitHub→Railway (зараз вручну) | низький |
| 5 | Команда `/review` для пакетного перегляду непідтверджених good/bad | низький |
| 6 | Webhook алерти в реальному часі (зараз тільки cron щодоби) | низький |
| 7 | Тижневі/місячні звіти з графіками | низький |

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

# Railway redeploy (через GraphQL з токеном)
curl -s -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -d '{"query":"mutation { serviceInstanceDeployV2(serviceId:\"47310987-04a1-4e95-a974-a13fc599da33\", environmentId:\"c52fafba-7011-483a-93db-afceb9c15667\") }"}'
```

---

## 14. Ключі і доступи (всі в `.env` локально + Railway Variables)

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
| `DAILY_REPORT_TIME` | `09:00` (не використовується, cron hardcoded на 06:00) |

Railway Token, GitHub PAT, Anthropic key — у локальному `.env` (НЕ комітити!).

---

## 15. Контактні точки

- Telegram бот: `@managers_analytics_bot`
- Email Supabase алерти: `tycoon.dmitriy1@gmail.com`
- GitHub owner: `Dmytro-tycoon`
- Railway team: `dmytro-tycoon's Projects`

---

**Останнє оновлення:** 04.06.2026, після виправлення timezone у форматуванні діалогу для Claude.
