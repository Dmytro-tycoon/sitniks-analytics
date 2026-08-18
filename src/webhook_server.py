"""HTTP-сервер для Sitniks webhooks. Слухає POST /webhook/sitniks."""
import os
import json
from aiohttp import web

from src.sitniks.client import SitniksClient
from src.analyzer.spam_filter import is_spam_profile
from src.config import settings

SPAM_TAG = "🚫 SPAM"
# Дедуплікація сповіщень про спам — щоб не спамити Telegram при кожному повідомленні
_NOTIFIED_SPAM_CHATS: set[str] = set()

# ── Автовітання gift-воронки (Telegram-канал SKIN.ONE) ──────────────────────────
# initialSource нашого бот-каналу в Sitniks (перевірено на живому чаті).
GIFT_SOURCE = "telegram_bot"
GIFT_WELCOME_TEXT = (
    'Вітаємо! 🎁 Напишіть у відповідь „Хочу подарунок" — '
    'і наш спеціаліст незабаром приєднається до розмови. 😊'
)
# Дедуплікація автовітання — один раз на чат (у межах життя процесу).
_WELCOMED_CHATS: set[str] = set()


async def handle_webhook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    # Sitniks payload: точну структуру дізнаємось з логів першого виклику.
    # Часті варіанти: payload["chatId"], payload["chat"]["id"], payload["data"]["chatId"]
    chat_id = (
        payload.get("chatId")
        or (payload.get("chat") or {}).get("id")
        or (payload.get("data") or {}).get("chatId")
        or (payload.get("data") or {}).get("chat", {}).get("id")
    )
    print(f"[webhook] payload keys={list(payload.keys())} chat_id={chat_id}", flush=True)
    # Повний payload для діагностики false-positives (тимчасово)
    try:
        print(f"[webhook] RAW payload: {json.dumps(payload, ensure_ascii=False)[:1500]}", flush=True)
    except Exception:
        pass

    if not chat_id:
        return web.json_response({"ok": True, "note": "no chatId"})

    sc = SitniksClient()
    try:
        chat = await sc.get_chat(chat_id)
        is_spam, reason = is_spam_profile(chat.get("userName"), chat.get("userNickName"))

        if is_spam:
            existing_tags = chat.get("tags") or []
            if SPAM_TAG not in existing_tags:
                new_tags = existing_tags + [SPAM_TAG]
                try:
                    await sc.update_chat_tags(chat_id, new_tags)
                    print(f"[webhook] 🚫 SPAM detected & tagged: {chat.get('userName')} (@{chat.get('userNickName')}) — {reason}", flush=True)
                except Exception as e:
                    print(f"[webhook] tag failed: {e}", flush=True)

            # Сповіщаємо тебе в Telegram — лише один раз на чат
            if chat_id not in _NOTIFIED_SPAM_CHATS:
                from src.telegram_bot.bot import bot
                client_link = f'<a href="https://web.sitniks.com/2341/chats/dialog/{chat_id}">{chat.get("userName") or "—"} (@{chat.get("userNickName") or "—"})</a>'
                print(f"[webhook] TELEGRAM SEND about SPAM: {chat.get('userName')} (@{chat.get('userNickName')}) reason={reason}", flush=True)
                try:
                    await bot.send_message(
                        settings.TELEGRAM_SHADOW_CHAT_ID or settings.TELEGRAM_LEADERSHIP_CHAT_ID,
                        f"🚫 <b>СПАМ-чат</b>\n{client_link}\nприсвоєно тег <code>{SPAM_TAG}</code>\nпричина: {reason}",
                        parse_mode="HTML", disable_web_page_preview=True,
                    )
                    _NOTIFIED_SPAM_CHATS.add(chat_id)
                    if len(_NOTIFIED_SPAM_CHATS) > 10000:
                        _NOTIFIED_SPAM_CHATS.clear()
                except Exception as e:
                    print(f"[webhook] tg notify failed: {e}", flush=True)
        else:
            print(f"[webhook] ✓ not spam: {chat.get('userName')} (@{chat.get('userNickName')})", flush=True)

        # ── Автовітання для Telegram gift-воронки ───────────────────────────────
        # Шлемо один раз на чат, тільки для нашого бот-каналу і поки менеджер ще
        # не відповів. Наша ж відповідь іде як повідомлення менеджера, але dedup-
        # множина гарантує, що вітання не спрацює вдруге (захист від зациклення).
        if (
            not is_spam
            and chat.get("initialSource") == GIFT_SOURCE
            and chat_id not in _WELCOMED_CHATS
        ):
            try:
                msgs = await sc.get_chat_messages(chat_id)
                # Менеджерські повідомлення мають непорожній managerName; наше ж
                # автовітання йде з порожнім managerName (sentBy = id бота), тому
                # додатково перевіряємо, чи текст вітання вже є в чаті — це переживає
                # рестарт процесу (коли _WELCOMED_CHATS порожня).
                manager_replied = any((m.get("managerName") or "").strip() for m in msgs)
                already_welcomed = any((m.get("text") or "") == GIFT_WELCOME_TEXT for m in msgs)
                if not manager_replied and not already_welcomed:
                    await sc.send_message(chat_id, GIFT_WELCOME_TEXT)
                    print(f"[webhook] 🎁 welcome sent to telegram chat {chat_id}", flush=True)
                else:
                    print(f"[webhook] 🎁 skip welcome (manager_replied={manager_replied}, already={already_welcomed}) {chat_id}", flush=True)
                _WELCOMED_CHATS.add(chat_id)
                if len(_WELCOMED_CHATS) > 10000:
                    _WELCOMED_CHATS.clear()
            except Exception as e:
                print(f"[webhook] welcome failed for {chat_id}: {e}", flush=True)

    except Exception as e:
        print(f"[webhook] error processing {chat_id}: {e}", flush=True)
    finally:
        await sc.close()

    return web.json_response({"ok": True})


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/sitniks", handle_webhook)
    app.router.add_get("/", handle_health)
    # LiqPay callback (ізольований пакет, реєструє /liqpay/callback + /liqpay/health)
    from src.liqpay.callback import register_liqpay_routes
    register_liqpay_routes(app)
    return app


async def run_web():
    runner = web.AppRunner(make_app())
    await runner.setup()
    port = int(os.getenv("PORT", "8000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[webhook] server listening on 0.0.0.0:{port}", flush=True)
