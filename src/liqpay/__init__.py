"""LiqPay «Оплата частинами» — ізольований пакет.

Складові:
  client.py   — підпис LiqPay, генерація checkout-URL, перевірка callback
  store.py    — зберігання замовлень + журнал подій (Supabase) з ідемпотентністю
  bot.py      — aiogram-бот (діалог /pay, /orders); експортує liqpay_bot, liqpay_dp
  callback.py — aiohttp-роут /liqpay/callback (реєструється у webhook_server)

Свідомо не перетинається з рештою ботів: власний Dispatcher, власні таблиці
(`liqpay_*`), власний префікс callback_data (`lp_...`).
"""
