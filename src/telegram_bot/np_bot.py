"""
Telegram-бот для роботи з кабінетами Нової Пошти.

Команди:
  /registry  — створити реєстр відправлень з чернеток
  /start     — інструкція
"""
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.config import settings
from src.novaposhta.client import NovaPooshtaClient

np_dp = Dispatcher()
np_bot: Optional[Bot] = None

if settings.NP_BOT_TOKEN:
    np_bot = Bot(
        token=settings.NP_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


class RegistryFlow(StatesGroup):
    selecting_account = State()
    confirming = State()


def _only_operator(message: Message) -> bool:
    return message.chat.id == settings.NP_OPERATOR_CHAT_ID


def _account_keyboard() -> InlineKeyboardMarkup:
    accounts = settings.NP_ACCOUNTS
    buttons = [
        [InlineKeyboardButton(text=acc["name"], callback_data=f"np_acc:{i}")]
        for i, acc in enumerate(accounts)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Створити реєстр", callback_data="np_reg:confirm"),
        InlineKeyboardButton(text="❌ Скасувати", callback_data="np_reg:cancel"),
    ]])


def _format_draft_list(drafts: list, account_name: str) -> str:
    lines = [f"📦 <b>Чернетки: {account_name}</b>", f"Знайдено: {len(drafts)} ТТН\n"]
    for doc in drafts[:30]:  # показуємо перші 30, щоб не переповнити повідомлення
        lines.append(f"• {doc}")
    if len(drafts) > 30:
        lines.append(f"\n<i>...та ще {len(drafts) - 30} ТТН</i>")
    lines.append("\nСтворити реєстр з усіх цих ТТН?")
    return "\n".join(lines)


# ── /start ────────────────────────────────────────────────────────────────────

@np_dp.message(Command("start"))
async def cmd_start(message: Message):
    if not _only_operator(message):
        return
    await message.answer(
        "📮 <b>Бот Нової Пошти</b>\n\n"
        "• /registry — створити реєстр з чернеток"
    )


# ── /registry ─────────────────────────────────────────────────────────────────

@np_dp.message(Command("registry"))
async def cmd_registry(message: Message, state: FSMContext):
    if not _only_operator(message):
        return

    accounts = settings.NP_ACCOUNTS
    if not accounts:
        await message.answer("❌ NP_ACCOUNTS не налаштовано в .env")
        return

    if len(accounts) == 1:
        # Один акаунт — одразу шукаємо чернетки
        await state.update_data(account_index=0)
        await _fetch_and_show_drafts(message, state, 0)
    else:
        await state.set_state(RegistryFlow.selecting_account)
        await message.answer(
            "Оберіть кабінет НП:",
            reply_markup=_account_keyboard(),
        )


@np_dp.callback_query(RegistryFlow.selecting_account, F.data.startswith("np_acc:"))
async def cb_select_account(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    await callback.message.edit_reply_markup(reply_markup=None)
    await _fetch_and_show_drafts(callback.message, state, idx)
    await callback.answer()


async def _fetch_and_show_drafts(message: Message, state: FSMContext, account_index: int):
    accounts = settings.NP_ACCOUNTS
    account = accounts[account_index]

    await message.answer(f"⏳ Шукаю чернетки в <b>{account['name']}</b>...")

    client = NovaPooshtaClient(account["key"])
    try:
        drafts = await client.get_drafts(days_back=7)
    except Exception as e:
        await message.answer(f"❌ Помилка НП API: {e}")
        await state.clear()
        return
    finally:
        await client.close()

    if not drafts:
        await message.answer(
            f"📭 Чернеток у <b>{account['name']}</b> не знайдено "
            f"(за останні 7 днів)."
        )
        await state.clear()
        return

    await state.set_state(RegistryFlow.confirming)
    await state.update_data(
        account_index=account_index,
        draft_refs=[d.ref for d in drafts],
    )
    await message.answer(
        _format_draft_list(drafts, account["name"]),
        reply_markup=_confirm_keyboard(),
    )


@np_dp.callback_query(RegistryFlow.confirming, F.data == "np_reg:confirm")
async def cb_confirm_registry(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)

    data = await state.get_data()
    account_index = data["account_index"]
    draft_refs = data["draft_refs"]
    account = settings.NP_ACCOUNTS[account_index]

    await callback.message.answer(
        f"⏳ Створюю реєстр ({len(draft_refs)} ТТН) у <b>{account['name']}</b>..."
    )
    await state.clear()

    client = NovaPooshtaClient(account["key"])
    try:
        registry = await client.create_registry(draft_refs)
    except Exception as e:
        await callback.message.answer(f"❌ Не вдалося створити реєстр: {e}")
        await client.close()
        return

    number_str = f"№ <code>{registry.number}</code>" if registry.number else f"(ref: <code>{registry.ref}</code>)"
    await callback.message.answer(
        f"✅ <b>Реєстр створено</b>\n\n"
        f"Кабінет: {account['name']}\n"
        f"Реєстр: {number_str}\n"
        f"ТТН включено: {len(draft_refs)}"
    )

    # Тягнемо офіційний PDF-бланк зі штрихкодом і шлемо документом
    try:
        pdf_bytes = await client.download_registry_pdf(registry.ref)
        file_name = f"Реєстр_{registry.number or registry.ref}.pdf"
        await callback.message.answer_document(
            BufferedInputFile(pdf_bytes, filename=file_name),
            caption="📄 Бланк реєстру для друку",
        )
    except Exception as e:
        await callback.message.answer(f"⚠️ Реєстр створено, але PDF не вдалося завантажити: {e}")
    finally:
        await client.close()

    await callback.answer()


@np_dp.callback_query(RegistryFlow.confirming, F.data == "np_reg:cancel")
async def cb_cancel_registry(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await callback.message.answer("Скасовано.")
    await callback.answer()
