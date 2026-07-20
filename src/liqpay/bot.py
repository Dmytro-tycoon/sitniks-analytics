"""
Telegram-бот LiqPay «Оплата частинами» (aiogram).

Команди:
  /pay     — діалог: сума → опис → готове посилання «оплата частинами»
  /orders  — історія замовлень цього чату
  /start   — довідка

Доступ обмежено списком операторів (LIQPAY_OPERATOR_CHAT_IDS).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.config import settings
from src.liqpay import store
from src.liqpay.client import LiqPay, build_payparts_payment

liqpay_dp = Dispatcher()
liqpay_bot: Optional[Bot] = None
_liqpay: Optional[LiqPay] = None

if settings.LIQPAY_BOT_TOKEN:
    liqpay_bot = Bot(
        token=settings.LIQPAY_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
if settings.LIQPAY_PUBLIC_KEY and settings.LIQPAY_PRIVATE_KEY:
    _liqpay = LiqPay(settings.LIQPAY_PUBLIC_KEY, settings.LIQPAY_PRIVATE_KEY)


STATUS_LABEL = {
    "created": "🆕 створено (не оплачено)",
    "success": "✅ оплачено",
    "wait_accept": "⏳ очікує підтвердження",
    "processing": "⏳ обробляється",
    "hold_wait": "🔒 заблоковано (hold)",
    "subscribed": "✅ підписка",
    "failure": "❌ не пройшов",
    "error": "❌ помилка",
    "reversed": "↩️ повернуто",
}


class PayFlow(StatesGroup):
    waiting_amount = State()
    waiting_description = State()


def _only_operator(message: Message) -> bool:
    ids = settings.LIQPAY_OPERATOR_CHAT_IDS
    return message.chat.id in ids if ids else True


def _make_order_id(chat_id: int) -> str:
    return f"tg-{chat_id}-{int(time.time())}"


# ── /start ──────────────────────────────────────────────────────────────────────

@liqpay_dp.message(Command("start"))
async def cmd_start(message: Message):
    if not _only_operator(message):
        return
    await message.answer(
        "💳 <b>LiqPay — оплата частинами</b>\n\n"
        "• /pay — створити посилання на оплату частинами\n"
        "• /orders — історія твоїх замовлень\n"
        "• /cancel — скасувати поточний ввід"
    )


@liqpay_dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    if not _only_operator(message):
        return
    await state.clear()
    await message.answer("❌ Скасовано. Натисни /pay, щоб почати знову.")


# ── /pay ────────────────────────────────────────────────────────────────────────

@liqpay_dp.message(Command("pay"))
async def cmd_pay(message: Message, state: FSMContext):
    if not _only_operator(message):
        return
    if _liqpay is None:
        await message.answer("❌ LIQPAY_PUBLIC_KEY / LIQPAY_PRIVATE_KEY не налаштовані в .env")
        return
    await state.set_state(PayFlow.waiting_amount)
    await message.answer(
        "Введи <b>суму</b> платежу в гривнях (напр. <code>1500</code> або <code>1499.99</code>).\n"
        "Скасувати — /cancel"
    )


@liqpay_dp.message(PayFlow.waiting_amount)
async def step_amount(message: Message, state: FSMContext):
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = round(float(raw), 2)
    except ValueError:
        await message.answer("⚠️ Це не схоже на число. Введи суму, напр. <code>1500</code>.")
        return
    if amount <= 0:
        await message.answer("⚠️ Сума має бути більшою за 0.")
        return

    await state.update_data(amount=amount)
    await state.set_state(PayFlow.waiting_description)
    await message.answer(
        f"Сума: <b>{amount:.2f} грн</b> ✅\n\n"
        "Тепер введи <b>опис</b> платежу (напр. <i>Замовлення №123</i>)."
    )


@liqpay_dp.message(PayFlow.waiting_description)
async def step_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    if not description:
        await message.answer("⚠️ Опис не може бути порожнім. Введи текст опису.")
        return

    data = await state.get_data()
    amount = data["amount"]
    order_id = _make_order_id(message.chat.id)

    params = build_payparts_payment(
        amount=amount,
        order_id=order_id,
        description=description,
        paytype=settings.LIQPAY_PAYTYPE,
        result_url=settings.LIQPAY_RESULT_URL or None,
        server_url=settings.LIQPAY_SERVER_URL or None,
    )
    url = _liqpay.checkout_url(params)

    try:
        await asyncio.to_thread(
            store.create_order,
            order_id=order_id,
            chat_id=message.chat.id,
            amount=amount,
            currency="UAH",
            description=description,
            paytype=settings.LIQPAY_PAYTYPE,
            payment_url=url,
        )
    except Exception as e:  # noqa: BLE001 — не блокуємо видачу посилання через збій БД
        print(f"[liqpay] create_order failed: {e}", flush=True)

    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💳 Оплатити частинами", url=url)
    ]])
    await message.answer(
        "✅ <b>Посилання на оплату частинами готове!</b>\n\n"
        f"Сума: <b>{amount:.2f} грн</b>\n"
        f"Опис: {description}\n"
        f"Order ID: <code>{order_id}</code>\n\n"
        f"🔗 {url}",
        reply_markup=kb,
        disable_web_page_preview=True,
    )


# ── /orders ─────────────────────────────────────────────────────────────────────

@liqpay_dp.message(Command("orders"))
async def cmd_orders(message: Message):
    if not _only_operator(message):
        return
    try:
        orders = await asyncio.to_thread(store.list_orders_by_chat, message.chat.id, 10)
    except Exception as e:  # noqa: BLE001
        await message.answer(f"❌ Не вдалося отримати замовлення: {e}")
        return

    if not orders:
        await message.answer("📭 У тебе ще немає замовлень. Натисни /pay, щоб створити перше.")
        return

    lines = ["🧾 <b>Останні замовлення</b> (до 10):\n"]
    for o in orders:
        created = _fmt_created(o.get("created_at"))
        status = STATUS_LABEL.get(o.get("status", ""), o.get("status", ""))
        desc = (o.get("description") or "").strip()
        try:
            amount = float(o.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        lines.append(
            f"• <b>{amount:.2f} {o.get('currency', 'UAH')}</b> — {status}\n"
            f"  {desc}\n"
            f"  <code>{o.get('order_id', '')}</code> · {created}"
        )
    await message.answer("\n".join(lines), disable_web_page_preview=True)


def _fmt_created(value) -> str:
    """created_at з Supabase — ISO-рядок; акуратно форматуємо у ДД.ММ.РРРР ГГ:ХХ."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(value)[:16]
