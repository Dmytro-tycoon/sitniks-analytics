# Сесія 06.06.2026 — Бот аналітики рекламних постів

## Мета

Створити окремий Telegram-бот, який щоранку показує, **з яких рекламних об'яв були оформлені замовлення в Sitniks** за минулий день.

---

## Як це працює (логіка атрибуції)

```
Order (з /orders Sitniks)
   └─ chatId
       └─ перше повідомлення чату (/chats/{id}/messages)
           └─ adInfo.adTitle  ← назва рекламної об'яви
```

У Sitniks API кожне повідомлення, яке прийшло з реклами Instagram/Facebook, має поле `adInfo`:

```json
"adInfo": {
  "adId": "120253775599570059",
  "adTitle": "Face Cream HUBISLAB 29.04.2026 (широка 23.03)",
  "source": "ADS",
  "type": "OPEN_THREAD"
}
```

Якщо в чаті нема `adInfo` → замовлення йде в категорію **"Без реклами (прямі)"**.

---

## Що додано в код

### 1. `src/sitniks/client.py`
Новий метод `get_ad_info_for_chat(chat_id)` — тягне перші 5 повідомлень чату і повертає перший знайдений `adInfo` (бо рекламний пост приходить з самим першим повідомленням клієнта).

### 2. `src/analyzer/ad_analytics.py` (новий)
- `build_ad_report(date_from, date_to)` — групує замовлення за `adTitle`
- `format_ad_report(report)` — форматує HTML-звіт для Telegram з медалями 🥇🥈🥉
- Concurrency: `asyncio.Semaphore(3)` + `sleep(0.1)` між запитами (захист від 429)

### 3. `src/telegram_bot/ads_bot.py` (новий)
Окремий бот **@skinone_advertising_bot** (назва: "Замовлення з реклами").

Команди:
- `/start` — інструкція
- `/ads` — звіт за вчора
- `/ads 2026-06-04` — за конкретну дату
- `/ads_today` — за сьогодні (наживо)
- `/whoami` — chat_id (для налаштування груп)

Також `send_daily_ads_report()` — функція для cron-розсилки.

### 4. `src/main.py`
Два боти тепер запускаються паралельно через `asyncio.gather()`:
```python
tasks = [dp.start_polling(bot)]
if settings.ADS_BOT_TOKEN:
    tasks.append(ads_dp.start_polling(ads_bot))
await asyncio.gather(*tasks)
```

### 5. `src/scheduler/jobs.py`
Новий cron-job `daily_ads_report`:
- **06:30 Київ** (на 30 хв пізніше за основний звіт о 06:00, щоб уникнути конкуренції за Sitniks API)
- Викликає `send_daily_ads_report()`

### 6. `src/config.py`
Додано `ADS_BOT_TOKEN` і `ADS_REPORT_CHAT_ID` як properties.

### 7. `scripts/test_ad_analytics.py`
Ручний тест: `python scripts/test_ad_analytics.py [days_back]`

---

## Інфраструктура

| Параметр | Значення |
|---|---|
| Bot username | `@skinone_advertising_bot` |
| Bot токен | `ADS_BOT_TOKEN` (env, у Railway Variables + локальному `.env`) |
| Telegram група | **Skin.One замовлення з реклами** (chat_id `-5138355367`) |
| Розклад | щодня **06:30 Київ** |
| Хостинг | той самий Railway service (`bot`), що й основний бот |
| Railway API token | `RAILWAY_TOKEN` (у локальному `.env`) — для деплою через GraphQL |

---

## Приклад звіту (за 04.06.2026)

```
📣 Замовлення по рекламних постах за 04.06.2026
Всього замовлень: 37

🥇 Без реклами (прямі)
   → 12 замовлень (32%)
🥈 🌺Терапевтичні креми 20.04.2026 мода + життя
   → 3 замовлень (8%)
🥉 🔥Омолоджувальне комбо🔥 22.12.2025 мода+жизнь
   → 3 замовлень (8%)
▪️ 🟢Крем з вітаміном К USOLAB 29.04.2026 (Lookalike 3)
   → 2 замовлень (5%)
...
```

---

## Чому 06:30, а не 06:00

Основний job `daily_analysis_job` о 06:00 за перші ~5-10 хв тягне всі чати + повідомлення з Sitniks. Якщо запускати ads-job паралельно, обидва б'ються об rate-limit (429), отримують ретраї → все працює довше.

О 06:30 основний job уже на фазі **очікування Claude batch** (5-15 хв), Sitniks API вільне.

---

## Виправлені/виявлені моменти

1. **Python 3.9 на Railway** не підтримує синтаксис `dict | None` → змінено на `Optional[dict]` (з `typing`)
2. **Telegram message limit 4096** → додано функцію `_chunks()` для розбиття довгих звітів
3. **Bot privacy mode** — за замовчуванням в групі бот не читає звичайні повідомлення, але **команди (з `/`) завжди отримує** — не довелось вимикати privacy

---

## Деплой (як це робилось)

Через Railway GraphQL API з токеном `RAILWAY_TOKEN`:

```bash
# Додати env-змінну
curl -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -d '{"query":"mutation { variableUpsert(input: {projectId:\"...\", environmentId:\"...\", serviceId:\"...\", name:\"ADS_BOT_TOKEN\", value:\"...\"}) }"}'

# Тригернути redeploy
curl -X POST https://backboard.railway.com/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" \
  -d '{"query":"mutation { serviceInstanceDeployV2(serviceId:\"47310987-04a1-4e95-a974-a13fc599da33\", environmentId:\"c52fafba-7011-483a-93db-afceb9c15667\") }"}'
```

---

## Комміти

| Hash | Опис |
|---|---|
| `f163c78` | feat: separate Telegram bot for ad-post analytics |
| `b24022e` | chore: move ads report to 06:30 Kyiv |

---

## TODO / на майбутнє

- [ ] **Зберігати `ad_title` в Supabase** (нова колонка в `dialog_analyses` або окрема таблиця `ad_orders`) — для історичних трендів та графіків
- [ ] **Тижневий/місячний звіт** — найкращі рекламні об'яви за період
- [ ] **Розкладка по менеджерах** — які менеджери закривають з якої реклами
- [ ] **ROI**: якщо буде доступ до бюджетів Facebook Ads — рахувати вартість замовлення з кожної об'яви
- [ ] **Розділення по бренду** (`skin.one.ua` vs `skin.one.hair`) — зараз все в одній купі

---

**Створено:** 06.06.2026
