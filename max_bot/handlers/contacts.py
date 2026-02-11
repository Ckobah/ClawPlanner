import logging

from max_bot.compat import InlineKeyboardButton, InlineKeyboardMarkup
from max_bot.context import MaxContext, MaxUpdate

from database.db_controller import db_controller
from entities import MaxUser
from i18n import resolve_user_locale, tr

logger = logging.getLogger(__name__)


def _normalize_participants(participants: dict[int, str] | dict[str, str] | None) -> dict[int, str]:
    normalized: dict[int, str] = {}
    for raw_user_id, name in (participants or {}).items():
        try:
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            continue
        normalized[user_id] = name
    return normalized


def _normalize_selected(selected: list[int] | list[str] | set[int] | set[str] | None) -> set[int]:
    normalized: set[int] = set()
    for raw_user_id in (selected or []):
        try:
            normalized.add(int(raw_user_id))
        except (TypeError, ValueError):
            continue
    return normalized


def _build_team_keyboard(participants: dict[int, str], selected: set[int], locale: str | None = None) -> InlineKeyboardMarkup:
    buttons = []
    for tg_id, name in participants.items():
        postfix = " ❌" if tg_id in selected else ""
        buttons.append([InlineKeyboardButton(f"{name}{postfix}", callback_data=f"team_toggle_{tg_id}")])

    buttons.append([InlineKeyboardButton(tr("Удалить выбранных", locale), callback_data="team_delete")])
    buttons.append([InlineKeyboardButton(tr("Закрыть", locale), callback_data="team_close")])

    return InlineKeyboardMarkup(buttons)


async def handle_team_command(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("handle_team_command")
    context.chat_data.pop("team_participants", None)
    context.chat_data.pop("team_selected", None)
    context.chat_data.pop("event", None)
    context.chat_data.pop("participants_status", None)
    context.chat_data.pop("time_picker_message_id", None)
    context.chat_data.pop("time_picker_chat_id", None)
    context.chat_data.pop("await_time_input", None)
    context.chat_data.pop("time_input_prompt_message_id", None)
    context.chat_data.pop("time_input_prompt_chat_id", None)
    user_id = update.effective_chat.id
    locale = await resolve_user_locale(user_id, platform="max")

    participants = _normalize_participants(await db_controller.get_participants(tg_id=user_id, include_inactive=True, platform="max"))
    message = update.message or (update.callback_query.message if update.callback_query else None)
    if not participants:
        text = tr("У вас нет участников.", locale)
        if message:
            await message.reply_text(text)
        else:
            await context.bot.send_message(text=text, user_id=user_id)
        return

    context.chat_data["team_participants"] = participants
    context.chat_data["team_selected"] = []

    reply_markup = _build_team_keyboard(participants, set(), locale=locale)
    text = tr("Список участников. Выберите лишних и нажмите Удалить.", locale)
    if message:
        await message.reply_text(text, reply_markup=reply_markup)
    else:
        await context.bot.send_message(text=text, user_id=user_id, attachments=reply_markup.to_attachments())

async def handle_team_callback(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("handle_team_callback")
    query = update.callback_query
    await query.answer()

    user_id = update.effective_chat.id
    locale = await resolve_user_locale(user_id, platform="max")
    data = query.data

    participants = _normalize_participants(
        context.chat_data.get("team_participants")
        or await db_controller.get_participants(tg_id=user_id, include_inactive=True, platform="max")
        or {}
    )
    selected = _normalize_selected(context.chat_data.get("team_selected"))

    if data.startswith("team_toggle_"):
        _, _, tg_id_str = data.split("_")
        tg_id = int(tg_id_str)
        if tg_id in selected:
            selected.remove(tg_id)
        else:
            selected.add(tg_id)

        context.chat_data["team_selected"] = list(selected)
        reply_markup = _build_team_keyboard(participants, selected, locale=locale)
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return

    if data == "team_delete":
        if not selected:
            await query.edit_message_text(
                tr("Выберите участников для удаления.", locale),
                reply_markup=_build_team_keyboard(participants, selected, locale=locale),
            )
            return

        deleted = await db_controller.delete_participants(
            current_tg_id=user_id,
            related_tg_ids=list(selected),
            platform="max",
        )
        participants = _normalize_participants(
            await db_controller.get_participants(tg_id=user_id, include_inactive=True, platform="max") or {}
        )
        context.chat_data["team_participants"] = participants
        context.chat_data["team_selected"] = []

        if not participants:
            await query.edit_message_text(tr("Все участники удалены.", locale))
            return

        reply_markup = _build_team_keyboard(participants, set(), locale=locale)
        await query.edit_message_text(
            tr("Удалено: {count}. Выберите новых участников.", locale).format(count=deleted),
            reply_markup=reply_markup,
        )
        return

    if data == "team_close":
        context.chat_data.pop("team_participants", None)
        context.chat_data.pop("team_selected", None)
        await query.edit_message_text(tr("Управление участниками закрыто.", locale))
        return

async def handle_contact(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("handle_contact")
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="max")

    contact = getattr(update.message, "contact", None)
    logger.info("MAX contact payload: %s", contact)
    if isinstance(contact, dict):
        class _Contact:
            pass

        normalized = _Contact()
        normalized.user_id = contact.get("user_id") or contact.get("id")
        normalized.first_name = contact.get("first_name") or contact.get("name")
        normalized.last_name = contact.get("last_name")
        normalized.phone_number = contact.get("phone_number") or contact.get("phone")
        contact = normalized
    if contact and contact.user_id:
        try:
            contact.user_id = int(contact.user_id)
        except (TypeError, ValueError):
            logger.info("MAX contact user_id not numeric: %s", contact.user_id)
    if contact and not contact.user_id:
        await update.message.reply_text(tr("Похоже этот номер не зарегистрирован в телеграмм!", locale))
    elif contact:
        user_id = contact.user_id
        if user_id == update.effective_chat.id:
            await update.message.reply_text(tr("Нельзя добавлять себя", locale))
            return
        first_name = contact.first_name
        last_name = contact.last_name
        # phone_number = contact.phone_number
        new_user = MaxUser(
            id=user_id,
            first_name=first_name,
            last_name=last_name,
        )
        created_user = await db_controller.save_update_max_user(max_user=new_user, from_contact=True, current_user=update.effective_chat.id)
        if not created_user:
            text = tr("Пользователь {name} уже добавлен в ваши контакты!", locale).format(name=first_name)
        elif created_user.is_active:
            text = tr("Пользователь {name} добавлен в ваши контакты!", locale).format(name=first_name)
        else:
            text = (
                tr("Пользователь {name} добавлен в ваши контакты!", locale).format(name=first_name) + "\n"
                + tr(
                    "Отправьте ему приглашение в FamPlanner_bot. Вы сможете добавлять его, как участника события, после того как он нажмет START. Перешлите ему следующее сообщение:",
                    locale,
                )
            )
            invite_text = (
                tr(
                    "Привет!\nДавай вместе создавать события и строить планы!\nЗапусти бота и нажми START.\nВот ссылка: https://t.me/FamPlanner_bot",
                    locale,
                )
            )

        await db_controller.get_user(tg_id=update.effective_chat.id, platform="max")

        await update.message.reply_text(text=text)
        if "invite_text" in locals():
            await update.message.reply_text(text=invite_text)

        event = context.chat_data.get("event")
        if event:
            participants = _normalize_participants(await db_controller.get_participants(
                tg_id=update.effective_chat.id, include_inactive=True, platform="max"
            ) or {})
            event.all_user_participants = participants
            context.chat_data["event"] = event

            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton(tr("Продолжить создание события", locale), callback_data="create_event_begin_")]]
            )
            await update.message.reply_text(
                tr("Участник добавлен в контакты. Можно продолжить создание события.", locale),
                reply_markup=reply_markup,
            )
    else:
        await update.message.reply_text(tr("Не удалось получить данные пользователя, попробуйте еще раз", locale))
