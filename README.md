# Sitniks Analytics

Аналіз діалогів менеджерів у Sitniks CRM через Claude + Telegram звіти.

## Стек
- Python 3.9+
- Sitniks Open API
- Anthropic Claude (Sonnet)
- Supabase (PostgreSQL)
- aiogram (Telegram бот)
- APScheduler (щоденний cron о 09:00 Київ)

## Запуск
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заповни ключі
python -m src.main
```

## Команди бота
- `/today` — звіт за сьогодні
- `/yesterday` — звіт за вчора
- `/manager <ім'я>` — звіт по менеджеру
- `/whoami` — chat_id поточного чату
