# Sitniks Analytics

Автоматичний аналіз діалогів менеджерів у Sitniks CRM:
**Sitniks → Claude AI → Supabase → Telegram звіти**.

## Що робить

1. О 09:00 за київським часом тягне всі діалоги за вчорашній день із Sitniks Open API.
2. Кожен діалог аналізується Claude Sonnet за 7 критеріями (швидкість, тон, виявлення потреби, експертність, заперечення, закриття, допродаж).
3. Підраховуються кількісні метрики (час відповіді, conversion).
4. Зведення зберігається в Supabase.
5. У Telegram приходять:
   - 📊 Зведений звіт у групу "Керівництво"
   - 👤 Особистий звіт кожному менеджеру в приватку

## Команди Telegram-бота

| Команда | Дія |
|---|---|
| `/start` | Меню команд |
| `/today` | Звіт за сьогодні |
| `/yesterday` | Звіт за вчора |
| `/manager <ім'я>` | Особистий звіт по менеджеру за вчора |
| `/whoami` | Показати chat_id поточного чату |

## Інфраструктура

| Сервіс | Призначення |
|---|---|
| **Railway** | Хостинг бота 24/7. Проєкт `sitniks-analytics`, service `bot`. |
| **Supabase** | БД для збереження аналізів. Проєкт `sitniks-analytics`. |
| **GitHub** | Код: `Dmytro-tycoon/sitniks-analytics`. |
| **Anthropic Claude** | Модель `claude-sonnet-4-6`. Кешування системного промпта. |
| **Sitniks Open API** | Джерело діалогів. |

## Як змінити критерії оцінки

Без редеплою: відкрий Supabase → таблиця `criteria` → редагуй поле `content`.

З редеплоєм: редагуй `src/claude/prompts.py` → push в GitHub → запусти redeploy на Railway.

## Як додати/змінити менеджера

Railway → service `bot` → Variables → редагуй `TELEGRAM_MANAGERS`:
```json
{"Єлизавета": 521207705, "Віка Палатай": 427263576, "Нове Ім'я": 12345}
```
Збережи — service автоматично перезапуститься.

## Локальний запуск (для розробки)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заповни ключі
python -m src.main
```

## Стек

- Python 3.9+, asyncio
- `aiogram` 3.22 (Telegram)
- `anthropic` 0.40 (Claude API)
- `supabase-py` 2.9 (Supabase)
- `httpx` (Sitniks API)
- `APScheduler` (cron)

## Версії

- **v1.0 (29.05.2026)** — MVP: щоденні звіти, 7 критеріїв, retry на rate-limit Anthropic.

## Що далі (roadmap)

- [ ] Додати еталонні діалоги в промпт (few-shot) — підвищить якість оцінок
- [ ] Розподіл менеджерів по брендах (skin.one.ua / skin.one.hair)
- [ ] Алерти в реальному часі (webhooks замість cron)
- [ ] Дашборд (Vercel) для перегляду метрик
- [ ] Тижневі/місячні звіти з динамікою
