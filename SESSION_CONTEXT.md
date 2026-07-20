# Sitniks Analytics — контекст сесії

> Документ описує стан системи аналітики менеджерів станом на 13.07.2026.
> Призначений для швидкого відновлення контексту при наступному запуску роботи.

---

## 1. Що це за проєкт

Автоматичний аналіз діалогів менеджерів-косметологів у Sitniks CRM:
**Sitniks → Claude AI (Batch) → Supabase → Telegram звіти + real-time spam filter + AI-coach + RAG**.

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

Це навмисні бренд-псевдоніми, **не** помилки. Прописано у промпті + `clients/skin_one.context.md`.

---

## 2. Інфраструктура

| Сервіс | Призначення | Ключові ID |
|---|---|---|
| **Railway** | Хостинг 24/7 (worker + HTTP) | project `sitniks-analytics`, service `bot`, env `production`, **публічна URL** `https://bot-production-71cc6.up.railway.app` |
| **Supabase** | БД (Postgres) | project_id `igkemadfxebmcetxvhwx`, URL `https://igkemadfxebmcetxvhwx.supabase.co`, RLS увімкнено |
| **GitHub — sitniks-analytics** | Основний проєкт (аналітика + ads + spam + np + agent-integration) | https://github.com/Dmytro-tycoon/sitniks-analytics |
| **GitHub — sales-agent** | Приватний окремий репо чистого AI-агента (шаблон для повторного розгортання) | https://github.com/Dmytro-tycoon/sales-agent |
| **Anthropic Claude** | Аналіз (Batch API — `-50%`, max_wait=4h) | `claude-sonnet-4-6` (основний), `claude-haiku-4-5` (post-класифікація) |
| **Sitniks Open API** | Джерело даних + write (send_message) | `https://crm.sitniks.com/open-api`, Bearer token |
| **Sitniks Webhooks** | Real-time події ("Повідомлення в чаті" → POST на `/webhook/sitniks`) | |

**Cron (Europe/Kiev):**
- `daily_analysis_job` — щодня **05:30** (був 06:00)
- `send_daily_ads_report` — щодня **08:30**
- `reattribute_yesterday` (коригування ads-атрибуції) — **22:00**
- `daily_hair_stats_job` — **05:30** (Google Sheets, зараз падає — див. §10)

---

## 3. Структура коду

```
src/
  config.py                 # multi-tenant (YAML + .context.md з clients/)
  main.py                   # entrypoint: scheduler + telegram + web + ads_bot + np_bot
  webhook_server.py         # aiohttp сервер для Sitniks webhook (spam-filter)
  sitniks/
    client.py               # HTTP client + retry на 429 + send_message()
    parser.py               # format_dialog_for_claude (час → Київ)
  claude/
    client.py               # ClaudeAnalyzer single
    batch.py                # ClaudeBatchAnalyzer (Batch API, max_wait=14400s = 4h)
    prompts.py              # NAШ analysis-промпт
    sales_prompts.py        # від sales-agent (SCORE_KEYS/LABELS + coach/rag/tone)
    llm.py                  # тонкий JSON-обгортка для coach/rag/agent
  database/
    supabase_client.py      # CRUD + spam-tag + tone + agent_feedback
  analyzer/
    filter.py               # should_analyze() — фільтр коротких/порожніх
    spam_filter.py          # is_spam_profile() — евристика по name/nick
    metrics.py              # час відповіді + count_client_msgs_in_work_hours
    pipeline.py             # analyze_period() — orchestration
    insights.py             # hot_leads, lost_clients, alerts, leaderboard, trends
    aggregator.py           # aggregate_by_manager
    ad_analytics.py         # build_ad_report + "Стара атрибуція"
    stats_pipeline.py       # hair stats → Google Sheets (падає без сервіс-акаунту)
  consultant/               # АГЕНТ-КОНСУЛЬТАНТ (КВАЛІФІКАТОР) — окремий пакет
    engine.py               # respond / followup_message (кваліфікація + handoff, кеш)
    guardrails.py           # ESCALATE_TRIGGERS + каденція дожимів
    memory.py               # Conversation state (status: active|handoff|escalated|lost)
    playbook.py             # тон+прийоми кваліфікації з tone_of_voice (qualify_only)
    prompts.py              # QUALIFIER_SYSTEM_PROMPT + FOLLOWUP_PROMPT
    pricecards.py           # пошук картки товару на запит «Ціна?» (find_card)
    handoff.py              # передача живому консультанту (Telegram-анкета + тег Sitniks)
    channels/               # канали доставки агента (НЕ запускаються в main)
      sitniks_seller.py     # полінг чатів Sitniks
      telegram_sales.py     # окремий Telegram-бот (пісочниця/бій)
  coach/
    advisor.py              # /reco /plan /objection /reply
  rag/
    knowledge.py            # /ask /faq (лексичний пошук + Claude)
  crm/
    base.py                 # CRMConnector Protocol (Dialog / Message)
    sitniks.py              # SitniksConnector з send_message
  telegram_bot/
    bot.py                  # /today /yesterday /manager + 11 нових команд + feedback
    reports.py              # format_daily_report + format_manager_report
    insights_reports.py     # format_alerts/leaderboard/hot/lost/objections/trends
    ads_bot.py              # окремий бот-Ads
    np_bot.py               # Nova Poshta bot
  novaposhta/               # NP client
  sheets/                   # Google Sheets client (для hair stats)
  scheduler/
    jobs.py                 # 4 cron-задачі
```

---

## 4. Схема Supabase

### `dialog_analyses`
- `dialog_id` (TEXT, UNIQUE)
- `dialog_date`, `manager_name`, `client_username`, `client_name`
- `has_order` (legacy)
- `messages_count`, `messages_from_manager`, `client_msgs_in_work_hours`
- `avg_response_minutes`, `max_response_minutes`, `first_response_minutes`, `duration_minutes`
- `scores` (JSONB), `overall_score`
- `alerts` (JSONB), `strengths`, `improvements`, `summary`, `is_template_dialog`
- `dialog_quality` ('good'|'bad'|'neutral'), `quality_reason`
- `user_confirmed`, `user_comment`, `user_feedback_at` (feedback loop)

### `daily_reports` — агрегати за день
### `criteria` — критерії системи (single row)
### `telegram_users` — авто-збір chat_id з `catch_all` handler
### `reported_ad_orders` — щоб не дублювати ads-звіт
### `chat_owner_cache` — кеш для sitniks_owner
### `tone_of_voice` — playbook від успішних діалогів (для sales-agent)
### `agent_feedback` — окрема таблиця для sales-agent feedback (не плутати з user_confirmed у dialog_analyses)

---

## 5. Метрики (поточна логіка)

**"Усього діалогів" = Нові чати + Чинні з замовленням** (Sitniks-дашборд логіка):
- **Нові чати** = `firstMessageStartDate/EndDate` window
- **Чинні з замовленням** = chatId з orders за день, які НЕ потрапили в нові

**Реальна кількість замовлень** — з `/orders` API через `responsible.user.fullname`.
Прив'язка order ↔ chat — через `chatId` поле у /orders.

---

## 6. Економія Claude

Стартова вартість ~$270/міс → зараз ~$60-70/міс:
1. **Batch API** — `-50%` (max_wait=14400s = 4h, після інциденту з timeout 12.07)
2. **Фільтр коротких** (menager not responded / no client / <2 msgs → skip)
3. **Скорочений JSON output** (`max_tokens=1500`)
4. **Prompt caching** на SYSTEM_PROMPT

---

## 7. Anthropic

**Tier 2** досягнуто. Потрібно періодично поповнювати баланс — інакше batch падає з
`credit_balance_too_low` (як було 22.06–23.06).

---

## 8. Telegram-звіт: формат

**Щоранку о 05:30 Київ** в групу "Керівництво":
1. Загальний звіт (один message): показники + рейтинг + критичні алерти + 🔇 "Менеджер не відповів" (тільки де клієнт писав у робочий час 08:00–23:00 Київ)
2. **2 хороших + 3 поганих** приклади з inline-кнопками:
   - **✅ Згоден** → `user_confirmed=true`
   - **❌ Не згоден** → ForceReply просить коментар → парсинг через regex `🆔 ([0-9a-f]{24})`

**Особисті звіти менеджерам:** через **TELEGRAM_SHADOW_CHAT_ID** = 448547265 (Dmitriy) —
всі звіти йдуть тобі з префіксом `📋 Звіт для {ім'я}`. Менеджерам напряму НЕ розсилаємо.

**Лінки на чати в Sitniks:** `https://web.sitniks.com/2341/chats/dialog/{dialog_id}`.

---

## 9. Sales-agent модулі (додано 03.07)

### 11 нових команд у боті
| Категорія | Команда | Дія |
|---|---|---|
| 📊 | `/leaderboard` | Рейтинг за 7 днів (композитний якість×конверсія) |
| 📊 | `/trends` | Динаміка за 8 тижнів |
| 🚨 | `/alerts` | Що потребує уваги сьогодні |
| 🚨 | `/hot` | Гарячі ліди без замовлення |
| 🚨 | `/lost` | Втрачені клієнти + причини |
| 🚨 | `/objections` | Топ заперечень |
| 🤝 | `/reco Ім'я` | Рекомендації РОПу по менеджеру |
| 🤝 | `/plan Ім'я` | Персональний план зростання |
| 🤝 | `/objection <текст>` | 2 варіанти відповіді на заперечення |
| 🧠 | `/ask <питання>` | Q&A по всіх переписках з цитатами |
| 🧠 | `/faq` | Часті питання клієнтів |

### Multi-tenant конфіг
- `clients/skin_one.yaml` — моделі, критерії, менеджери
- `clients/skin_one.context.md` — бізнес-контекст (~2 кБ) підмішується у coach/rag/agent
- Env `CLIENT=skin_one` вибирає активну пару

### Окремий репозиторій sales-agent
https://github.com/Dmytro-tycoon/sales-agent (приватний, 54 файли) — чистий шаблон агента,
який можна повторно розгорнути під іншого клієнта.

---

## 10. Real-time spam-фільтр

**Webhook URL:** `https://bot-production-71cc6.up.railway.app/webhook/sitniks`
**Подія Sitniks:** "Повідомлення в чаті" (Instagram + інші джерела)

**Виправлений баг** (08.06): раніше блок TELEGRAM SEND був під `else`, тобто сповіщення
йшли **тільки на НЕ спам** (false positives). Виправлено — тепер повідомлення про SPAM
приходять тільки на реальний спам.

**Спам-патерни** (`src/analyzer/spam_filter.py`):
- ім'я: `support`, `business`, `chat ai`, `assistant`, `helpdesk`, `crypto/bitcoin/forex...`, `verified/claim/prize`
- нік: `_love\d*`, `_official\d*`, `_bot\d*`, `chat_/bot_/support_/ai_` префікси

Дедуплікація через `_NOTIFIED_SPAM_CHATS` (in-memory).

---

## 11. Ads-звіт (щодня 08:30 Київ)

Формат сумісний з Sitniks-дашбордом:
1. 📣 **Основний блок** — реклами з adInfo ≤ 30 днів до замовлення
2. 🕰 **Стара атрибуція** (>30 днів) — окрема секція, без медалей, тільки інформація

`chatId` з `/orders` дозволяє точно матчити order ↔ ad (немає fuzzy-логіки).
`STALE_AD_DAYS = 30` у `src/analyzer/ad_analytics.py`.

Cron `reattribute_yesterday` (22:00 Київ) — Sitniks дозаповнює `adInfo` із затримкою,
о 22:00 перераховуємо і шлемо коригуючий алерт якщо були зміни.

---

## 12. Sitniks Open API — write доступ

**14.07 Sitniks додав `POST /open-api/chats/{chatId}/messages`** (`ChatsOpenApiController_sendChatMessage`).

Body: `{ "text": string, "attachments": [string]? }` → Response 201 + створене повідомлення.

**Реалізовано в двох клієнтах:**
- `src/sitniks/client.py:SitniksClient.send_message()` — з `_post_with_retry` (429 backoff)
- `src/crm/sitniks.py:SitniksConnector.send_message()` — з sales-agent

**Ще НЕ використовується у production** — обговорили безпечний потік:
1. **Крок 1**: разово протестувати send_message на тестовому чаті
2. **Крок 2** (**Shadow Mode**): webhook → agent готує чернетку → шле в Telegram Дмитру з
   кнопками "✅ Відправити / ✏️ Редагувати / ❌ Не потрібно" → тільки після кліку
   викликається `sitniks.send_message()`
3. **Крок 3** (згодом): для стабільних сценаріїв — автовідправка без кнопки

Ще не почато. Користувач сказав "трохи пізніше повернемось".

**Що поки НЕ дав Sitniks:**
- `assignedManagerId` у `PUT /chats/{id}` (для автопризначення спам-чатів на керівника).
  У листі-запиті цей пункт прибрали, щоб не розпорошувати увагу.

---

## 13. Feedback loop і калібрування

- Кожен good/bad приклад у щоденному звіті — окреме повідомлення з кнопками ✅/❌
- При ❌ — ForceReply просить коментар, зберігається в `user_comment`
- Уже пройдено **3 ітерації калібрування промпта** на основі коментарів
- Головні правила (у `src/claude/prompts.py`):
  - Опт/B2B/косметолог-перепродавець → завжди `neutral`
  - Замовлення є → залежить від overall_score та експертності (bad тільки при критичних провалах)
  - Клієнт замовк → NOT `bad` (це не помилка менеджера)
  - Робочий час 08:00–23:00 Київ
  - "Анастасія" / "Катерина" — бренд-імена, не обман

---

## 14. Виявлені інженерні баги і виправлення

| Дата | Баг | Виправлення |
|---|---|---|
| 08.06 | Spam webhook блок TELEGRAM SEND був під `else` — сповіщення на НЕ спам | Перенесено під `if is_spam:` |
| 05.06 | `get_chat_messages` віддавав тільки 10 з 75+ | Пагінація limit=50, скіп, сортування |
| 05.06 | Sitniks 429 rate-limit при daily-job | Retry exp backoff в `_get_with_retry` + concurrency=2 |
| 05.06 | UTC vs Київ у часових мітках | `to_kiev_str()` + явне `(Київ)` у промпті |
| 05.06 | CR-6 алерт про >5000 грн — Claude вгадував без даних | Прибрано з промпта |
| 05.06 | "Менеджер не відповів" включав порожні чати | Фільтр `client_msgs_in_work_hours > 0` |
| 04.06 | cron у UTC замість Києва | `CronTrigger(timezone=KIEV_TZ)` явно |
| 04.06 | RLS попередження Supabase | RLS увімкнено на всіх таблицях (`service_role` bypass) |
| 22–23.06 | Не пройшли звіти | Anthropic баланс закінчився → повідомили → поповнено |
| **13.07** | Не пройшов звіт за **12.07** | Batch не завершився за 1 год (`TimeoutError`). Збільшено `max_wait` в `src/claude/batch.py`: **3600s → 14400s (4h)**. Ретрозапуск через `run_now.py 2026-07-12` — звіт прийшов. |

---

## 15. Що в TODO

| # | Що | Пріоритет |
|---|---|---|
| 1 | **Shadow Mode для автовідповідей** (тестування send_message + agent-workflow) | високий (як тільки скажеш) |
| 2 | `daily_hair_stats_job` падає з `google-service-account.json not found` — треба додати сервіс-акаунт у Railway або вимкнути cron | середній |
| 3 | Знову попросити Sitniks — `assignedManagerId` у `PUT /chats/{id}` (для антиспам-автоперепризначення) | середній |
| 4 | Розширити analysis-промпт щоб видавав `buying_intent`, `client_sentiment`, `objections`, `lost_reason` — /hot /lost /objections матимуть свіжі дані (зараз частково працюють) | середній |
| 5 | ✅ **ЗРОБЛЕНО** — playbook з `good`-діалогів (`scripts/build_playbook.py` → `tone_of_voice.voice/winning_moves/objection_playbook` → `consultant/playbook.py` у промпт). Каталог товарів з orders (`scripts/build_product_kb.py` → `clients/skin_one.products*.md`). Періодично регенерувати. | — |
| 6 | Auto-deploy GitHub → Railway (зараз ручний mutation) | низький |
| 7 | Скіли Claude Code (`.claude/skills/onboarding`, `setup`) — auto-mode блокує копіювання, потрібен явний дозвіл | низький |
| 8 | Команда `/review` для пакетного перегляду непідтверджених good/bad | низький |
| 9 | Тижневі/місячні звіти з графіками | низький |

---

## 16. Корисні команди

```bash
# Локальний запуск (дебаг)
cd ~/Documents/sitniks-analytics
source venv/bin/activate
python -m src.main

# Разовий аналіз за конкретну дату (ретрозапуск при пропущеному дні)
python scripts/run_now.py 2026-07-12

# Перекласифікувати існуючі записи (Haiku)
python scripts/classify_existing.py 2026-07-12

# Агент-консультант: оновити каталог товарів з реальних orders (топ-60 у промпт)
PYTHONPATH=. python scripts/build_product_kb.py 120 60

# Агент-консультант: намайнити плейбук з good-діалогів → tone_of_voice (ідемпотентно)
PYTHONPATH=. python scripts/build_playbook.py 30 7

# Агент-консультант: картки товарів для відповіді на «Ціна?» (з реальних відповідей дівчат)
PYTHONPATH=. python scripts/mine_price_cards.py 60 150   # → clients/skin_one.price_cards.md

# Пісочниця агента-консультанта (окремий Telegram-бот)
PYTHONPATH=. python scripts/run_sales_bot.py

# Тестовий webhook payload
curl -X POST https://bot-production-71cc6.up.railway.app/webhook/sitniks \
  -H "Content-Type: application/json" \
  -d '{"chat":{"id":"6a...."},"message":{}}'

# Railway redeploy
curl -s -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -d '{"query":"mutation { serviceInstanceDeployV2(serviceId:\"47310987-04a1-4e95-a974-a13fc599da33\", environmentId:\"c52fafba-7011-483a-93db-afceb9c15667\") }"}'
```

---

## 17. Env vars (усі в локальному `.env` + Railway Variables)

| Змінна | Значення / Місце |
|---|---|
| `CLIENT` | `skin_one` (вибір активної пари з `clients/`) |
| `SITNIKS_API_KEY` | див. локальний `.env` |
| `SITNIKS_API_URL` | `https://crm.sitniks.com/open-api` |
| `ANTHROPIC_API_KEY` | див. локальний `.env` |
| `TELEGRAM_BOT_TOKEN` | див. локальний `.env` |
| `TELEGRAM_LEADERSHIP_CHAT_ID` | `-5124563660` |
| `TELEGRAM_MANAGERS` | JSON 4 менеджерів |
| `TELEGRAM_SHADOW_CHAT_ID` | `448547265` (Dmitriy) — поки активно, звіти йдуть тобі |
| `TELEGRAM_SALES_BOT_TOKEN` | (окремий бот для пісочниці агента-консультанта) |
| `TELEGRAM_CONSULTANTS_CHAT_ID` | група дівчат-консультантів для анкет передачі (fallback → shadow/Дмитро) |
| `SUPABASE_URL` | `https://igkemadfxebmcetxvhwx.supabase.co` |
| `SUPABASE_SERVICE_KEY` | див. локальний `.env` |
| `ANALYSIS_TIMEZONE` | `Europe/Kiev` |
| `ADS_BOT_TOKEN` | окремий Telegram-бот для ads-звіту |
| `ADS_REPORT_CHAT_ID` | `-5138355367` (група для ads-звіту) |
| `NP_BOT_TOKEN`, `NP_OPERATOR_CHAT_ID`, `NP_ACCOUNTS` | Nova Poshta bot |
| `FB_ACCESS_TOKEN`, `GOOGLE_SERVICE_ACCOUNT_FILE`, `HAIR_STATS_SPREADSHEET_ID` | Hair stats (Google Sheets) |
| `PORT` | `8080` (Railway authoritative) |

Railway Token, GitHub PAT, Anthropic key, Sitniks key, Bot tokens — тільки в локальному `.env` (НЕ комітити!).

---

## 18. Контактні точки

- Telegram бот аналітики: `@managers_analytics_bot`
- Webhook Sitniks: `https://bot-production-71cc6.up.railway.app/webhook/sitniks`
- Health check: `https://bot-production-71cc6.up.railway.app/`
- Email Supabase алерти: `tycoon.dmitriy1@gmail.com`
- GitHub owner: `Dmytro-tycoon`
- Railway team: `dmytro-tycoon's Projects`

---

**Останнє оновлення:** 13.07.2026 — виправлено таймаут batch (1h → 4h), Sitniks додав send_message API, створено окремий приватний репо `sales-agent`, інтегровано sales-agent модулі у наш проект (11 нових команд), готово до Shadow Mode тестування автовідповідей.
