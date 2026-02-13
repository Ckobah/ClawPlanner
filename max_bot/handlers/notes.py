import logging
from datetime import datetime

from max_bot.compat import InlineKeyboardButton, InlineKeyboardMarkup
from max_bot.context import MaxContext, MaxUpdate

from database.db_controller import db_controller
from database.models.note_model import DbNote
from entities import MaxUser
from i18n import format_localized_datetime, resolve_user_locale, tr

logger = logging.getLogger(__name__)

NOTE_MAX_LENGTH = 3500
NOTE_PREVIEW_LENGTH = 40
PROMPT_PREVIEW_LENGTH = 1200


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit - 1]}…"


def _normalize_note_text(text: str | None) -> str:
    return (text or "").strip()


def _with_menu_row(rows: list[list[InlineKeyboardButton]], locale: str | None = None) -> InlineKeyboardMarkup:
    has_menu = any(btn.callback_data == "menu_open" for row in rows for btn in row)
    if not has_menu:
        rows.append([InlineKeyboardButton(tr("Меню", locale), callback_data="menu_open")])
    return InlineKeyboardMarkup(rows)


def _build_notes_markup(notes: list[DbNote], locale: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for note in notes:
        compact = " ".join(note.note_text.split())
        preview = _truncate(compact, NOTE_PREVIEW_LENGTH)
        rows.append([InlineKeyboardButton(preview or tr("Без текста", locale), callback_data=f"note_open_{note.id}")])
    rows.append([InlineKeyboardButton(tr("🗒Создать заметку", locale), callback_data="note_create")])
    return _with_menu_row(rows, locale)


def _build_note_detail_text(note: DbNote, locale: str | None = None) -> str:
    stamp_dt = note.updated_at or note.created_at or datetime.utcnow()
    stamp = format_localized_datetime(stamp_dt, locale=locale, fmt="d MMMM y, HH:mm")
    return tr("🗒 Заметка\n\n{note_text}\n\n🕒 Обновлено: {updated_at}", locale).format(
        note_text=note.note_text,
        updated_at=stamp,
    )


def _build_note_detail_markup(note_id: int, locale: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(tr("🔄 Редактировать", locale), callback_data=f"note_edit_{note_id}")],
        [InlineKeyboardButton(tr("❌ Удалить", locale), callback_data=f"note_delete_{note_id}")],
        [InlineKeyboardButton(tr("↩️ Назад", locale), callback_data="note_list")],
    ]
    return _with_menu_row(rows, locale)


def _parse_note_id(data: str, prefix: str) -> int | None:
    try:
        return int(data.removeprefix(prefix))
    except ValueError:
        return None


def _reset_note_states(context: MaxContext) -> None:
    context.chat_data.pop("await_note_create", None)
    context.chat_data.pop("await_note_edit", None)


def _build_waiting_input_markup(locale: str | None = None, back_callback: str = "note_list") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(tr("↩️ Назад", locale), callback_data=back_callback)]]
    return _with_menu_row(rows, locale)


async def _safe_delete_message(context: MaxContext, message_id: int | str | None) -> None:
    if message_id is None:
        return
    try:
        await context.bot.delete_message(message_id=message_id)
    except Exception:  # noqa: BLE001
        logger.exception("Cannot delete user message after note action")


async def _resolve_note_owner_id(max_id: int) -> int | None:
    return await db_controller.get_user_row_id(external_id=max_id, platform="max")


async def build_notes_list_view(owner_id: int, locale: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    notes = await db_controller.get_notes(user_id=owner_id)
    text = tr("Выберите заметку:", locale) if notes else tr("У вас пока нет заметок.", locale)
    return text, _build_notes_markup(notes, locale)


async def _show_notes_list_by_query(query, owner_id: int, locale: str | None = None) -> None:
    text, reply_markup = await build_notes_list_view(owner_id=owner_id, locale=locale)
    await query.edit_message_text(text=text, reply_markup=reply_markup)


async def show_notes(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("show_notes")
    _reset_note_states(context)
    context.chat_data.pop("await_event_description", None)
    context.chat_data.pop("await_time_input", None)

    if not update.effective_chat:
        return

    user = update.effective_chat
    max_user = MaxUser.model_validate(user)
    db_user = await db_controller.save_update_max_user(max_user=max_user)
    locale = await resolve_user_locale(user.id, platform="max", preferred_language_code=max_user.language_code)
    owner_id = await _resolve_note_owner_id(int(user.id))
    if owner_id is None:
        return
    logger.info(f"*** DB user: {db_user}")

    text, reply_markup = await build_notes_list_view(owner_id=owner_id, locale=locale)
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        return

    if update.message:
        await update.message.reply_text(text=text, reply_markup=reply_markup)


async def handle_note_callback(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("handle_note_callback")
    query = update.callback_query
    await query.answer()

    if not update.effective_chat:
        return

    user = update.effective_chat
    max_user = MaxUser.model_validate(user)
    db_user = await db_controller.save_update_max_user(max_user=max_user)
    locale = await resolve_user_locale(user.id, platform="max", preferred_language_code=max_user.language_code)
    owner_id = await _resolve_note_owner_id(int(user.id))
    if owner_id is None:
        return
    logger.info(f"*** DB user: {db_user}")
    data = query.data

    if data == "note_list":
        await _show_notes_list_by_query(query, owner_id=owner_id, locale=locale)
        return

    if data == "note_create":
        _reset_note_states(context)
        context.chat_data["await_note_create"] = {
            "source_message_id": getattr(query.message, "message_id", None),
        }
        await query.answer(tr("Режим создания заметки активен", locale), show_alert=False)
        await query.edit_message_text(
            text=tr("Режим создания заметки.\nОтправьте текст новым сообщением в чат.", locale),
            reply_markup=_build_waiting_input_markup(locale, back_callback="note_list"),
        )
        return

    if data.startswith("note_open_"):
        note_id = _parse_note_id(data, "note_open_")
        if note_id is None:
            await _show_notes_list_by_query(query, owner_id=owner_id, locale=locale)
            return
        note = await db_controller.get_note_by_id(note_id=note_id, user_id=owner_id)
        if not note:
            await _show_notes_list_by_query(query, owner_id=owner_id, locale=locale)
            return
        await query.edit_message_text(
            text=_build_note_detail_text(note, locale),
            reply_markup=_build_note_detail_markup(note.id, locale),
        )
        return

    if data.startswith("note_delete_"):
        note_id = _parse_note_id(data, "note_delete_")
        if note_id is not None:
            await db_controller.delete_note(note_id=note_id, user_id=owner_id)
        await _show_notes_list_by_query(query, owner_id=owner_id, locale=locale)
        return

    if data.startswith("note_edit_"):
        note_id = _parse_note_id(data, "note_edit_")
        if note_id is None:
            await _show_notes_list_by_query(query, owner_id=owner_id, locale=locale)
            return
        note = await db_controller.get_note_by_id(note_id=note_id, user_id=owner_id)
        if not note:
            await _show_notes_list_by_query(query, owner_id=owner_id, locale=locale)
            return

        _reset_note_states(context)
        prompt_note = _truncate(note.note_text, PROMPT_PREVIEW_LENGTH)
        context.chat_data["await_note_edit"] = {
            "note_id": note.id,
            "source_message_id": getattr(query.message, "message_id", None),
        }
        await query.answer(tr("Режим редактирования активен", locale), show_alert=False)
        edit_prompt = tr(
            "Режим редактирования заметки.\nОтправьте новый текст отдельным сообщением.\n\nТекущий текст:\n{note_text}",
            locale,
        ).format(note_text=prompt_note)
        await query.edit_message_text(
            text=edit_prompt,
            reply_markup=_build_waiting_input_markup(locale, back_callback=f"note_open_{note.id}"),
        )
        return

    await _show_notes_list_by_query(query, owner_id=owner_id, locale=locale)


async def handle_note_text_input(update: MaxUpdate, context: MaxContext, locale: str | None = None) -> bool:
    if not update.message or not update.effective_chat:
        return False

    state_create = context.chat_data.get("await_note_create")
    state_edit = context.chat_data.get("await_note_edit")
    if state_create is None and state_edit is None:
        return False

    locale = locale or await resolve_user_locale(update.effective_chat.id, platform="max")
    owner_id = await _resolve_note_owner_id(int(update.effective_chat.id))
    if owner_id is None:
        return True
    note_text = _normalize_note_text(update.message.text)
    if not note_text:
        await update.message.reply_text(tr("Текст заметки не может быть пустым.", locale))
        return True
    if len(note_text) > NOTE_MAX_LENGTH:
        await update.message.reply_text(
            tr("Слишком длинная заметка. Максимум {limit} символов.", locale).format(limit=NOTE_MAX_LENGTH)
        )
        return True

    if state_create is not None:
        await db_controller.create_note(user_id=owner_id, note_text=note_text)
        context.chat_data.pop("await_note_create", None)

        text, reply_markup = await build_notes_list_view(owner_id=owner_id, locale=locale)
        source_message_id = state_create.get("source_message_id")
        if source_message_id:
            await context.bot.edit_message(
                message_id=source_message_id,
                text=text,
                attachments=reply_markup.to_attachments(),
                locale=locale,
            )
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup)
        await _safe_delete_message(context, update.message.message_id)
        return True

    note_id = state_edit.get("note_id")
    if note_id is None:
        context.chat_data.pop("await_note_edit", None)
        await update.message.reply_text(tr("Заметка не найдена.", locale))
        await _safe_delete_message(context, update.message.message_id)
        return True

    note = await db_controller.update_note(note_id=note_id, user_id=owner_id, note_text=note_text)
    context.chat_data.pop("await_note_edit", None)

    if not note:
        await update.message.reply_text(tr("Заметка не найдена.", locale))
        await _safe_delete_message(context, update.message.message_id)
        return True

    text = _build_note_detail_text(note, locale)
    reply_markup = _build_note_detail_markup(note.id, locale)
    source_message_id = state_edit.get("source_message_id")
    if source_message_id:
        await context.bot.edit_message(
            message_id=source_message_id,
            text=text,
            attachments=reply_markup.to_attachments(),
            locale=locale,
        )
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)
    await _safe_delete_message(context, update.message.message_id)
    return True
