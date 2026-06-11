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
from aiogram.filters import Command, CommandObject
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


class EditFlow(StatesGroup):
    choosing_action = State()
    waiting_phone = State()
    waiting_name = State()
    confirming_cod_remove = State()


def _only_operator(message: Message) -> bool:
    ids = settings.NP_OPERATOR_CHAT_IDS
    return message.chat.id in ids if ids else True


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
        "• /registry — створити реєстр з чернеток\n"
        "• /edit <code>&lt;номер ТТН&gt;</code> — редагувати ТТН (телефон/ПІБ/НП)"
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


# ── /edit ─────────────────────────────────────────────────────────────────────

def _edit_keyboard(is_draft: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Змінити телефон", callback_data="np_edit:phone")],
        [InlineKeyboardButton(text="👤 Змінити ПІБ", callback_data="np_edit:name")],
        [InlineKeyboardButton(text="💰 Прибрати накладений платіж", callback_data="np_edit:cod")],
        [InlineKeyboardButton(text="❌ Закрити", callback_data="np_edit:cancel")],
    ])


def _format_doc_info(doc, account_name: str) -> str:
    raw = getattr(doc, "raw", {})
    phone = raw.get("RecipientsPhone", "—")
    addr = raw.get("RecipientAddressDescription", "") or doc.recipient_city or "—"
    state_name = raw.get("StateName", "—")
    try:
        cod_val = float(str(doc.cod or 0))
    except (ValueError, TypeError):
        cod_val = 0
    cod_line = f"{cod_val:.0f} грн" if cod_val > 0 else "немає"
    tag = "🟢 чернетка (зміни напряму)" if doc.is_draft else "🟠 на складі (зміни через заявку)"
    return (
        f"📦 <b>ТТН #{doc.number}</b>\n"
        f"Кабінет: {account_name}\n"
        f"Статус: {state_name}\n"
        f"Тип зміни: {tag}\n\n"
        f"Отримувач: {doc.recipient_name or '—'}\n"
        f"Телефон: {phone}\n"
        f"Адреса: {addr}\n"
        f"Накладений платіж: {cod_line}\n"
    )


@np_dp.message(Command("edit"))
async def cmd_edit(message: Message, command: CommandObject, state: FSMContext):
    if not _only_operator(message):
        return
    ttn = (command.args or "").strip()
    if not ttn or not ttn.isdigit():
        await message.answer("Формат: <code>/edit 20451459116069</code>")
        return

    await message.answer(f"⏳ Шукаю ТТН <code>{ttn}</code> в кабінетах…")

    accounts = settings.NP_ACCOUNTS
    found_doc = None
    found_idx = -1
    for i, acc in enumerate(accounts):
        client = NovaPooshtaClient(acc["key"])
        try:
            doc = await client.find_document(ttn)
            if doc:
                found_doc = doc
                found_idx = i
                break
        except Exception:
            pass
        finally:
            await client.close()

    if not found_doc:
        await message.answer("❌ ТТН не знайдено в жодному з кабінетів (за останні 60 днів).")
        return

    account = accounts[found_idx]
    await state.set_state(EditFlow.choosing_action)
    await state.update_data(
        account_index=found_idx,
        ttn=ttn,
        doc_ref=found_doc.ref,
        doc_raw=found_doc.raw,
        is_draft=found_doc.is_draft,
    )
    await message.answer(
        _format_doc_info(found_doc, account["name"]),
        reply_markup=_edit_keyboard(found_doc.is_draft),
    )


@np_dp.callback_query(EditFlow.choosing_action, F.data == "np_edit:cancel")
async def cb_edit_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await callback.answer("Закрито")


@np_dp.callback_query(EditFlow.choosing_action, F.data == "np_edit:phone")
async def cb_edit_phone(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(EditFlow.waiting_phone)
    await callback.message.answer("Введіть новий номер у форматі <code>380XXXXXXXXX</code>:")
    await callback.answer()


@np_dp.callback_query(EditFlow.choosing_action, F.data == "np_edit:name")
async def cb_edit_name(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(EditFlow.waiting_name)
    await callback.message.answer("Введіть нове ПІБ (Ім'я Прізвище По-батькові):")
    await callback.answer()


@np_dp.callback_query(EditFlow.choosing_action, F.data == "np_edit:cod")
async def cb_edit_cod(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.set_state(EditFlow.confirming_cod_remove)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Так, прибрати НП", callback_data="np_edit:cod_yes"),
        InlineKeyboardButton(text="❌ Ні", callback_data="np_edit:cod_no"),
    ]])
    await callback.message.answer("Точно прибрати накладений платіж?", reply_markup=kb)
    await callback.answer()


async def _apply_change(message: Message, state: FSMContext, **changes):
    """Виконує зміну (через update для чернетки або AdditionalService для прийнятої)."""
    data = await state.get_data()
    account = settings.NP_ACCOUNTS[data["account_index"]]
    client = NovaPooshtaClient(account["key"])
    try:
        if data["is_draft"]:
            await client.update_draft(data["doc_raw"], **changes)
            await message.answer("✅ Зміни збережено (чернетка, безкоштовно).")
        else:
            # Для зміни ПІБ NP API вимагає ще й телефон — беремо з ТТН якщо не передано
            current_phone = (data.get("doc_raw") or {}).get("RecipientsPhone", "")
            res = await client.request_change_after_accept(
                data["ttn"], current_phone=current_phone, **changes
            )
            ref = ""
            for item in res.get("data", []):
                ref = item.get("Ref", "") or ref
            await message.answer(
                "✅ Заявку на зміну створено.\n"
                + (f"№ заявки: <code>{ref}</code>\n" if ref else "")
                + "Зміни буде внесено до ЕН протягом кількох хвилин."
            )
    except Exception as e:
        await message.answer(f"❌ Помилка: {e}")
    finally:
        await client.close()
    await state.clear()


@np_dp.message(EditFlow.waiting_phone)
async def msg_new_phone(message: Message, state: FSMContext):
    phone = (message.text or "").strip().replace(" ", "").replace("-", "")
    if not phone.isdigit() or len(phone) < 10:
        await message.answer("❌ Невірний формат. Введіть <code>380XXXXXXXXX</code>:")
        return
    if not phone.startswith("380"):
        phone = "380" + phone.lstrip("0")
    await _apply_change(message, state, new_phone=phone)


@np_dp.message(EditFlow.waiting_name)
async def msg_new_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 4 or len(name.split()) < 2:
        await message.answer("❌ Введіть мінімум Ім'я та Прізвище:")
        return
    await _apply_change(message, state, new_name=name)


@np_dp.callback_query(EditFlow.confirming_cod_remove, F.data == "np_edit:cod_yes")
async def cb_cod_yes(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await _apply_change(callback.message, state, remove_cod=True)
    await callback.answer()


@np_dp.callback_query(EditFlow.confirming_cod_remove, F.data == "np_edit:cod_no")
async def cb_cod_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await callback.message.answer("Скасовано.")
    await callback.answer()
