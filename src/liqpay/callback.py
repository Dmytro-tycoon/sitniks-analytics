"""
aiohttp-роут для callback LiqPay (server_url).

LiqPay після зміни статусу платежу шле POST (form-urlencoded) з полями
`data` і `signature`. Ми: перевіряємо підпис → ідемпотентно пишемо подію →
оновлюємо статус → сповіщаємо оператора в Telegram.

Реєструється у наявному webhook-сервері:
    from src.liqpay.callback import register_liqpay_routes
    register_liqpay_routes(app)

Публічний URL (той самий, що для Sitniks-webhook):
    https://bot-production-71cc6.up.railway.app/liqpay/callback
"""

from __future__ import annotations

import asyncio
from typing import Optional

from aiohttp import web

from src.config import settings
from src.liqpay import store
from src.liqpay.client import LiqPay

_liqpay: Optional[LiqPay] = None
if settings.LIQPAY_PUBLIC_KEY and settings.LIQPAY_PRIVATE_KEY:
    _liqpay = LiqPay(settings.LIQPAY_PUBLIC_KEY, settings.LIQPAY_PRIVATE_KEY)

STATUS_TEXT = {
    "success": "✅ Оплату успішно отримано.",
    "wait_accept": "⏳ Гроші списані, очікуємо підтвердження.",
    "processing": "⏳ Платіж обробляється.",
    "hold_wait": "🔒 Кошти заблоковані (hold).",
    "subscribed": "✅ Підписку оформлено.",
    "failure": "❌ Платіж не пройшов.",
    "error": "❌ Помилка платежу.",
    "reversed": "↩️ Кошти повернуто.",
}


def _chat_id_from_order(order_id: str) -> Optional[int]:
    """order_id формату 'tg-<chat_id>-<ts>' -> chat_id."""
    try:
        parts = order_id.split("-")
        if len(parts) >= 3 and parts[0] == "tg":
            return int(parts[1])
    except (ValueError, AttributeError):
        pass
    return None


async def handle_liqpay_callback(request: web.Request) -> web.Response:
    if _liqpay is None:
        print("[liqpay] callback отримано, але ключі не налаштовані", flush=True)
        return web.json_response({"error": "not configured"}, status=503)

    form = await request.post()
    data = form.get("data")
    signature = form.get("signature")
    if not data or not signature:
        return web.json_response({"error": "no data/signature"}, status=400)

    try:
        payload = _liqpay.parse_callback(str(data), str(signature))
    except ValueError as exc:
        print(f"[liqpay] відхилено callback: {exc}", flush=True)
        # 200, щоб LiqPay не ретраїв підроблені запити
        return web.json_response({"ok": True, "note": "invalid signature"})

    status = payload.get("status", "")
    order_id = payload.get("order_id", "")
    amount = payload.get("amount")
    currency = payload.get("currency", "")
    payment_id = payload.get("payment_id")
    print(f"[liqpay] callback order={order_id} status={status} amount={amount} {currency} pid={payment_id}", flush=True)

    # Ідемпотентність: дубль тихо пропускаємо
    try:
        is_new = await asyncio.to_thread(
            store.record_payment_event, order_id, payment_id, status, amount, currency, payload
        )
    except Exception as e:  # noqa: BLE001
        print(f"[liqpay] record_payment_event failed: {e}", flush=True)
        return web.json_response({"ok": True, "note": "store error"})

    if not is_new:
        print(f"[liqpay] дублікат callback order={order_id} status={status} — пропуск", flush=True)
        return web.json_response({"ok": True, "note": "duplicate"})

    try:
        await asyncio.to_thread(store.update_order_status, order_id, status)
    except Exception as e:  # noqa: BLE001
        print(f"[liqpay] update_order_status failed: {e}", flush=True)

    chat_id = _chat_id_from_order(order_id)
    if chat_id is not None:
        from src.liqpay.bot import liqpay_bot
        if liqpay_bot is not None:
            human = STATUS_TEXT.get(status, f"Статус платежу: {status}")
            text = (
                f"{human}\n\n"
                f"Замовлення: <code>{order_id}</code>\n"
                f"Сума: <b>{amount} {currency}</b>"
            )
            try:
                await liqpay_bot.send_message(chat_id, text)
            except Exception as e:  # noqa: BLE001
                print(f"[liqpay] tg notify failed: {e}", flush=True)

    return web.json_response({"ok": True})


async def handle_liqpay_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "liqpay"})


def register_liqpay_routes(app: web.Application) -> None:
    """Додає роути LiqPay у наявний aiohttp-застосунок."""
    app.router.add_post("/liqpay/callback", handle_liqpay_callback)
    app.router.add_get("/liqpay/health", handle_liqpay_health)
