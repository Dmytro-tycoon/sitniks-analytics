"""Канал: агент-консультант у Sitniks.

Бот бере в роботу ТІЛЬКИ чати, що відповідають фільтру (_bot_should_take):
  • initialSource ∈ settings.AGENT_SOURCES (зараз — тільки "tiktok");
  • статус «новий» (settings.AGENT_NEW_STATUSES) АБО вже «в обробці ботом»
    (settings.AGENT_WORKING_STATUS — бот продовжує вести свій чат).
Решта статусів/джерел — дівчатам, бот не чіпає.

Робота зі СТАТУСАМИ (видно дівчатам у мобільному, де тегів не видно):
  • бере чат → ставить «🤖 В обробці Агентом» (дівчата бачать і не розбирають);
  • передає → ставить «🔥 Гарячий лід від Агента» (дівчата розбирають по статусу).
Взаємне виключення: у «новому» чаті бот відступає, лише якщо жива дівчина відповіла ПІСЛЯ
клієнтки. Авто-розсилку компанії на початку (менеджер перший, TikTok) бот НЕ рахує — бере чат.

Запуск: python scripts/run_sitniks_seller.py  (потрібні ключі Sitniks + Claude).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from src.consultant.engine import respond
from src.consultant.handoff import deliver_handoff
from src.consultant.memory import Conversation
from src.consultant import shadow
from src.consultant.pacing import human_pause
from src.consultant.playbook import get_playbook
from src.consultant.pricecards import is_price_question
from src.config import settings
from src.crm.base import Dialog, get_connector
from src.sitniks.client import SitniksClient

POLL_SECONDS = 25  # частіше — щоб бот встигав узяти новий чат раніше за дівчат (легко: чатів мало)


def _conv_from_dialog(dialog: Dialog) -> Conversation:
    conv = Conversation(lead_id=dialog.id, channel="sitniks")
    for m in dialog.messages:
        conv.add("client" if m.sender == "client" else "agent", m.text)
    return conv


def _needs_reply(dialog: Dialog) -> bool:
    return bool(dialog.messages) and dialog.messages[-1].sender == "client"


def _status_str(dialog: Dialog) -> str:
    st = dialog.status or (dialog.raw or {}).get("status") if dialog.raw else dialog.status
    if isinstance(st, dict):
        st = st.get("title")
    return (st or "").strip().lower()


def _source(dialog: Dialog) -> str:
    return ((dialog.raw or {}).get("initialSource") or "").strip().lower() if dialog.raw else ""


def _already_handed_off(dialog: Dialog) -> bool:
    """Чат уже передано дівчатам (статус «🔥 Гарячий лід від Агента») — бот не втручається."""
    return _status_str(dialog) == settings.AGENT_HANDOFF_STATUS.strip().lower()


def _human_replied(dialog: Dialog) -> bool:
    """Чи ЖИВА дівчина вже відпрацьовує чат — тобто менеджер відповів ПІСЛЯ клієнтки.

    Важливо для TikTok: багато чатів ініціює компанія авто-розсилкою (менеджерське
    повідомлення ПЕРШИМ, до відповіді клієнтки) — це НЕ живе відпрацювання, бот має брати.
    А якщо менеджер відповів уже після повідомлення клієнтки — це дівчина, бот не втручається."""
    seen_client = False
    for m in dialog.messages:
        if m.sender == "client":
            seen_client = True
        elif seen_client:  # менеджерська репліка після повідомлення клієнтки
            return True
    return False


def _bot_should_take(dialog: Dialog) -> bool:
    """Бот бере чат: потрібне джерело + статус «новий» (клеймить) або вже «в обробці ботом»
    (продовжує) + остання репліка від клієнтки + жива дівчина не зайшла першою.

    Мутекс: у «новому» чаті бот відступає, лише якщо менеджер відповів ПІСЛЯ клієнтки
    (жива дівчина). Авто-розсилку компанії на початку (менеджер перший) — бот НЕ рахує за
    відпрацювання й бере чат. Взявши, одразу ставить «в обробці» — наступні поли впізнають свій чат."""
    if _source(dialog) not in settings.AGENT_SOURCES:
        return False
    status = _status_str(dialog)
    if status == settings.AGENT_HANDOFF_STATUS.strip().lower():
        return False  # уже передано дівчатам
    is_new = status in settings.AGENT_NEW_STATUSES
    is_working = status == settings.AGENT_WORKING_STATUS.strip().lower()
    if not (is_new or is_working):
        return False  # взяла людина / інший статус
    if not _needs_reply(dialog):
        return False
    if is_new and _human_replied(dialog):
        return False  # дівчина вже відповідає клієнтці
    return True


async def _claim_chat(dialog: Dialog) -> None:
    """Поставити статус «🤖 В обробці Агентом», беручи чат у роботу. Ідемпотентно."""
    if _status_str(dialog) == settings.AGENT_WORKING_STATUS.strip().lower():
        return
    try:
        sc = SitniksClient()
        try:
            await sc.set_chat_status(dialog.id, settings.AGENT_WORKING_STATUS)
        finally:
            await sc.close()
    except Exception as e:
        print(f"[seller] claim status failed for {dialog.id}: {e}", flush=True)


async def process_chat(connector, dialog: Dialog, playbook: str) -> dict | None:
    """Згенерувати й відправити відповідь у конкретний чат Sitniks, за потреби — передати."""
    conv = _conv_from_dialog(dialog)

    # Претензія на чат: тег 🤖 БОТ, щоб дівчата не взяли його паралельно
    await _claim_chat(dialog)

    # На запит ціни підтягуємо заголовок реклами → правильна картка товару
    ad_title = None
    if is_price_question(conv.last_client_message()):
        try:
            sc = SitniksClient()
            try:
                ad = await sc.get_ad_info_for_chat(dialog.id)
            finally:
                await sc.close()
            ad_title = (ad or {}).get("adTitle")
        except Exception:
            pass

    result = await respond(conv, playbook=playbook, ad_title=ad_title)
    reply = result.get("reply", "")

    # На передачі клієнтці НІЧОГО не пишемо (для неї це та сама людина — далі веде дівчина).
    # Також не відповідаємо на ескалації. В інших випадках — відповідь клієнтці.
    if reply and not result.get("escalate") and not result.get("handoff"):
        nick = (dialog.raw or {}).get("userNickName") if dialog.raw else None
        if settings.SHADOW_MODE:
            # Shadow Mode: спершу чернетка Дмитру на підтвердження, клієнтці — після ✅
            await shadow.request_approval(dialog.id, reply, nick)
        else:
            await human_pause()  # «людська» затримка перед відповіддю
            await connector.send_message(dialog.id, reply)

    # Готова до підбору/замовлення → непомітно передаємо живому консультанту (тег + анкета)
    if result.get("handoff"):
        nick = (dialog.raw or {}).get("userNickName") if dialog.raw else None
        await deliver_handoff(dialog.id, "sitniks", result.get("handoff_summary") or "", nick)

    return result


def _chat_prefilter(c: dict) -> bool:
    """Дешевий фільтр за чат-обʼєктом (без повідомлень): джерело + статус.

    Дозволяє поллеру тягнути повідомлення ТІЛЬКИ для потенційно наших чатів (не всіх)."""
    src = (c.get("initialSource") or "").strip().lower()
    if src not in settings.AGENT_SOURCES:
        return False
    st = (c.get("status") or "").strip().lower()
    if st == settings.AGENT_HANDOFF_STATUS.strip().lower():
        return False
    return st in settings.AGENT_NEW_STATUSES or st == settings.AGENT_WORKING_STATUS.strip().lower()


async def poll_once(connector) -> int:
    now = datetime.now()
    dialogs = await connector.get_dialogs(now - timedelta(days=2), now, chat_filter=_chat_prefilter)
    playbook = get_playbook()
    handled = 0
    for d in dialogs:
        # пропускаємо чати з чернеткою на розгляді (Shadow Mode), щоб не дублювати
        if _bot_should_take(d) and not shadow.is_pending(d.id):
            await process_chat(connector, d, playbook)
            handled += 1
    return handled


async def _poll_loop(connector) -> None:
    while True:
        try:
            handled = await poll_once(connector)
            print(f"[seller] оброблено чатів: {handled}", flush=True)
        except Exception as e:
            print(f"[seller] poll error: {e}", flush=True)
        await asyncio.sleep(POLL_SECONDS)


async def run() -> None:
    if settings.SHADOW_MODE and shadow.shadow_bot is None:
        print("[seller] ⛔ SHADOW_MODE увімкнено, але SHADOW_BOT_TOKEN не заданий — "
              "нема куди слати чернетки. Задай SHADOW_BOT_TOKEN (або SHADOW_MODE=0 для авто). Вихід.", flush=True)
        return

    connector = get_connector(settings.crm_provider)
    mode = "SHADOW (чернетки на підтвердження)" if settings.SHADOW_MODE else "АВТО (пряма відправка)"
    print(f"Агент-консультант запущено (Sitniks). Режим: {mode}. Джерела: {settings.AGENT_SOURCES}")
    try:
        tasks = [_poll_loop(connector)]
        # У Shadow Mode паралельно крутимо бота підтверджень (кнопки Дмитра)
        if settings.SHADOW_MODE:
            tasks.append(shadow.run())
        await asyncio.gather(*tasks)
    finally:
        await connector.close()


if __name__ == "__main__":
    asyncio.run(run())
