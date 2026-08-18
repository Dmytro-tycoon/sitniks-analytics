"""Shadow Mode: бот не відправляє клієнтці сам, а спершу показує чернетку Дмитру.

Потік: агент згенерував відповідь → request_approval() шле її в Telegram (окремий бот)
з кнопками ✅ Відправити / ✏️ Редагувати / ❌ Не відповідати. Тільки після кліку:
  ✅ → SitniksClient.send_message() відправляє чернетку клієнтці;
  ✏️ → Дмитро надсилає виправлений текст → відправляється він;
  ❌ → бот НЕ відповідає, чат передається дівчатам (статус «🔥 Гарячий лід від Агента»).

Живе в тому самому процесі, що й поллер (run_sitniks_seller.py) — ділить стан _PENDING.
Потрібен окремий SHADOW_BOT_TOKEN (щоб не конфліктувати полінгом з основним ботом).
"""
from __future__ import annotations

import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.config import settings

shadow_bot: Bot | None = (
    Bot(token=settings.SHADOW_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    if settings.SHADOW_BOT_TOKEN
    else None
)
shadow_dp = Dispatcher()

# draft_id -> {"chat_id", "text", "nick"}
_DRAFTS: dict[str, dict] = {}
# чати з чернеткою на розгляді — поллер їх пропускає, щоб не дублювати
_PENDING_CHATS: set[str] = set()
# user_id -> draft_id, який зараз редагують
_EDITING: dict[int, str] = {}


def is_pending(chat_id: str) -> bool:
    return chat_id in _PENDING_CHATS


def _link(chat_id: str) -> str:
    return f"https://web.sitniks.com/2341/chats/dialog/{chat_id}"


async def _send_to_client(chat_id: str, text: str) -> None:
    import httpx

    from src.sitniks.client import SitniksClient

    sc = SitniksClient()
    try:
        await sc.send_message(chat_id, text)
    except httpx.HTTPStatusError as e:
        # показуємо ТІЛО відповіді Sitniks (там реальна причина, не просто «500»)
        raise RuntimeError(f"{e.response.status_code} — {e.response.text[:400]}") from e
    finally:
        await sc.close()


async def request_approval(chat_id: str, text: str, client_nick: str | None = None) -> bool:
    """Показати чернетку Дмитру з кнопками. True, якщо відправлено на розгляд."""
    if shadow_bot is None:
        print("[shadow] SHADOW_BOT_TOKEN не заданий — чернетку не показано, клієнтці НЕ відправлено", flush=True)
        return False
    if chat_id in _PENDING_CHATS:
        return False  # уже чекає на рішення

    did = uuid.uuid4().hex[:10]
    _DRAFTS[did] = {"chat_id": chat_id, "text": text, "nick": client_nick}
    _PENDING_CHATS.add(chat_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Відправити", callback_data=f"snd:{did}"),
        InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"edt:{did}"),
        InlineKeyboardButton(text="❌ Не відповідати", callback_data=f"cnl:{did}"),
    ]])
    who = f"@{client_nick}" if client_nick else chat_id
    await shadow_bot.send_message(
        settings.TELEGRAM_SHADOW_CHAT_ID,
        f"📝 <b>Чернетка відповіді</b> — {who}\n"
        f"<a href=\"{_link(chat_id)}\">чат у Sitniks →</a>\n\n{text}",
        reply_markup=kb,
        disable_web_page_preview=True,
    )
    return True


def _pop_draft(did: str) -> dict | None:
    d = _DRAFTS.pop(did, None)
    if d:
        _PENDING_CHATS.discard(d["chat_id"])
    return d


@shadow_dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Це бот Shadow Mode агента-консультанта.\n"
        "Сюди падатимуть чернетки відповідей — підтверджуй ✅ / редагуй ✏️ / відхиляй ❌.\n\n"
        f"chat_id: <code>{message.chat.id}</code>"
    )


@shadow_dp.callback_query(F.data.startswith("snd:"))
async def on_send(cb: CallbackQuery) -> None:
    did = cb.data.split(":", 1)[1]
    d = _DRAFTS.get(did)  # не викидаємо, поки не впевнимось, що відправилось
    if not d:
        await cb.answer("Чернетку не знайдено (застаріла)")
        return
    try:
        await _send_to_client(d["chat_id"], d["text"])
    except Exception as e:
        print(f"[shadow] SEND FAILED chat={d['chat_id']}: {e}", flush=True)  # у консоль — повна причина
        await cb.answer("Помилка — можна повторити ✅")
        await cb.message.answer(f"❌ Не вдалося відправити: {e}\n\nНатисніть ✅ ще раз, щоб повторити.")
        return
    _DRAFTS.pop(did, None)
    _PENDING_CHATS.discard(d["chat_id"])
    await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>Відправлено клієнтці</b>")
    await cb.answer("Відправлено")


@shadow_dp.callback_query(F.data.startswith("cnl:"))
async def on_cancel(cb: CallbackQuery) -> None:
    d = _pop_draft(cb.data.split(":", 1)[1])
    if d:
        # бот не веде цей чат далі → передаємо дівчатам
        from src.consultant.handoff import deliver_handoff

        await deliver_handoff(d["chat_id"], "sitniks", "Відхилено оператором — на підбір дівчатам.", d.get("nick"))
    await cb.message.edit_text(cb.message.html_text + "\n\n❌ <b>Не відправлено — передано дівчатам</b>")
    await cb.answer("Передано дівчатам")


@shadow_dp.callback_query(F.data.startswith("edt:"))
async def on_edit(cb: CallbackQuery) -> None:
    did = cb.data.split(":", 1)[1]
    if did not in _DRAFTS:
        await cb.answer("Чернетку не знайдено (застаріла)")
        return
    _EDITING[cb.from_user.id] = did
    await cb.message.answer("✏️ Надішліть виправлений текст відповіді:", reply_markup=ForceReply())
    await cb.answer()


@shadow_dp.message()
async def on_any_message(message: Message) -> None:
    """Ловимо виправлений текст (тільки якщо оператор натиснув ✏️)."""
    did = _EDITING.pop(message.from_user.id, None)
    if not did or not message.text:
        return
    d = _DRAFTS.get(did)
    if not d:
        await message.answer("Чернетку не знайдено (застаріла)")
        return
    try:
        await _send_to_client(d["chat_id"], message.text)
    except Exception as e:
        await message.answer(f"❌ Не вдалося відправити: {e}\n(чернетку збережено — можна натиснути ✅ під нею)")
        return
    _DRAFTS.pop(did, None)
    _PENDING_CHATS.discard(d["chat_id"])
    await message.answer("✅ Відправлено клієнтці (відредаговано)")


async def run() -> None:
    if shadow_bot is not None:
        await shadow_dp.start_polling(shadow_bot)
