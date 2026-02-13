import datetime
import logging
from datetime import date, time

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import TOKEN
from database.db_controller import db_controller
from entities import Event, Recurrent, TgUser
from i18n import format_localized_date, resolve_user_locale, tr

logger = logging.getLogger(__name__)

EMOJI_OPTIONS = [
    "💰",
    "🎉",
    "💤",
    "☠️",
    "⚡",
    "💪",
    "🎂",
    "🎮",
    "✈️",
    "‼️",
    "🎶",
    "💩",
    "🎭",
    "💣",
    "💊",
    "🏅",
    "📌",
    "🎁",
    "✈️",
    "🚂",
    "🛍️",
    "🏥",
    "🏖️",
    "🍽️",
    "🥂",
    "💐",
    "💃",
    "🏃‍♂️",
    "💇‍♀️",
    "💅",
]


def _event_snapshot(event: Event) -> dict:
    participants = sorted([int(item) for item in (event.participants or []) if item is not None])
    return {
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "stop_time": event.stop_time.isoformat() if event.stop_time else None,
        "description": event.description,
        "emoji": event.emoji,
        "recurrent": event.recurrent.value if event.recurrent else None,
        "participants": participants,
    }


def _event_has_changes(event: Event, original: dict | None) -> bool:
    if not original:
        return True
    return _event_snapshot(event) != original


def _get_back_button_state(context: ContextTypes.DEFAULT_TYPE, event: Event, year: int, month: int, day: int) -> tuple[bool, str | None]:
    if not context.chat_data.get("edit_event_id"):
        return False, None
    original = context.chat_data.get("edit_event_original")
    if not original:
        return False, None
    if _event_has_changes(event, original):
        return False, None
    return True, f"create_event_back_{year}_{month}_{day}"


def _build_delete_events_markup(
    events: list[tuple[str, int, bool]],
    selected_ids: set[int],
    year: int,
    month: int,
    day: int,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    list_btn = []
    for ev_text, ev_id, is_single in events:
        btn_text = ev_text
        if is_single and ev_id in selected_ids:
            btn_text = f"{btn_text} ❌"
        if not is_single:
            callback_data = f"delete_event_recurrent_{ev_id}_{year}_{month}_{day}"
            btn_text = f"{btn_text}*"
        else:
            callback_data = f"delete_event_select_{ev_id}_{year}_{month}_{day}"
        list_btn.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])

    if selected_ids:
        list_btn.append([InlineKeyboardButton(tr("🗑 Удалить", locale), callback_data=f"delete_event_confirm_{year}_{month}_{day}")])
    else:
        list_btn.append([InlineKeyboardButton(tr("Отмена", locale), callback_data=f"cal_select_{year}_{month}_{day}")])

    return InlineKeyboardMarkup(list_btn)


def build_emoji_keyboard(locale: str | None = None) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for idx, emoji in enumerate(EMOJI_OPTIONS):
        row.append(InlineKeyboardButton(emoji, callback_data=f"emoji_set_{idx}"))
        if len(row) == 6:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(tr("Без эмодзи", locale), callback_data="emoji_clear")])
    return InlineKeyboardMarkup(keyboard)


def format_description(description: str | None, locale: str | None = None) -> str:
    return description or tr("Описание *", locale)



def generate_time_selector(hours: int = 12, minutes: int = 0, time_type: str = "") -> InlineKeyboardMarkup:
    hours = hours % 24
    _show_min = minutes
    minutes = (minutes // 10) * 10  # Округляем до шага 10 минут
    minutes = minutes % 60

    keyboard = [
        [
            InlineKeyboardButton("▲", callback_data=f"time_hour_up_{time_type}_{hours}_{minutes}"),
            InlineKeyboardButton("▲", callback_data=f"time_minute_up_{time_type}_{hours}_{minutes}"),
        ],
        [
            InlineKeyboardButton(f"{hours:02d}", callback_data=f"time_hour_set_{time_type}"),
            InlineKeyboardButton(f"{_show_min:02d}", callback_data=f"time_minute_set_{time_type}"),
        ],
        [
            InlineKeyboardButton("▼️", callback_data=f"time_hour_down_{time_type}_{hours}_{minutes}"),
            InlineKeyboardButton("▼️", callback_data=f"time_minute_down_{time_type}_{hours}_{minutes}"),
        ],
        [InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")],
    ]

    return InlineKeyboardMarkup(keyboard)


async def handle_participants_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_participants_callback")
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")

    query = update.callback_query
    await query.answer()
    event: Event | None = context.chat_data.get("event")

    tg_id_income = int(query.data.split("_")[1])
    is_active = context.chat_data.get("participants_status", {}).get(tg_id_income, True)
    if not is_active:
        return

    if tg_id_income in event.participants:
        event.participants.remove(tg_id_income)
    else:
        event.participants.append(tg_id_income)

    context.chat_data["event"] = event

    list_btn = []
    for tg_id, name in event.all_user_participants.items():
        is_active = context.chat_data.get("participants_status", {}).get(tg_id, True)
        if not is_active:
            name = f"{name} ({tr('не в боте', locale)})"
        elif tg_id in event.participants:
            name = f"{name} ✅"
        list_btn.append([InlineKeyboardButton(name, callback_data=f"participants_{tg_id}")])

    list_btn.append([InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")])

    reply_markup = InlineKeyboardMarkup(list_btn)
    await query.edit_message_text(text=tr("Добавь пользователя, нажми скрепку", locale), reply_markup=reply_markup)



async def handle_emoji_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_emoji_callback")
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")

    query = update.callback_query
    await query.answer()

    event: Event | None = context.chat_data.get("event")
    if not event:
        return

    data = query.data
    if data == "emoji_open":
        await query.edit_message_text(text=tr("Выберите эмодзи:", locale), reply_markup=build_emoji_keyboard(locale))
        return

    if data.startswith("emoji_set_"):
        _, _, idx_str = data.split("_")
        idx = int(idx_str)
        if 0 <= idx < len(EMOJI_OPTIONS):
            event.emoji = EMOJI_OPTIONS[idx]
            context.chat_data["event"] = event
    elif data == "emoji_clear":
        event.emoji = None
        context.chat_data["event"] = event

    year, month, day = event.get_date()
    has_participants = bool(event.all_user_participants)
    show_back_btn, back_callback_data = _get_back_button_state(context, event, year, month, day)
    text, reply_markup = get_event_constructor(
        event=event,
        year=year,
        month=month,
        day=day,
        locale=locale,
        has_participants=has_participants,
        show_details=bool(context.chat_data.get("edit_event_id")),
        show_back_btn=show_back_btn,
        back_callback_data=back_callback_data,
    )
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")


async def handle_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_time_callback")
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")

    query = update.callback_query
    await query.answer()

    if query.message:
        context.chat_data["time_picker_message_id"] = query.message.message_id
        context.chat_data["time_picker_chat_id"] = query.message.chat_id

    event: Event | None = context.chat_data.get("event")

    data = query.data
    hours = 12
    minutes = 0

    if data.startswith("time_hour_set_"):
        _, _, _, time_type = data.split("_")
        message = await query.message.reply_text(tr("Введите часы (0-23):", locale))
        context.chat_data["await_time_input"] = {
            "field": "hour",
            "time_type": time_type,
            "prompt_message_id": message.message_id,
            "prompt_chat_id": message.chat_id,
        }
        context.chat_data["time_input_prompt_message_id"] = message.message_id
        context.chat_data["time_input_prompt_chat_id"] = message.chat_id
        return

    if data.startswith("time_minute_set_"):
        _, _, _, time_type = data.split("_")
        message = await query.message.reply_text(tr("Введите минуты (0-59):", locale))
        context.chat_data["await_time_input"] = {
            "field": "minute",
            "time_type": time_type,
            "prompt_message_id": message.message_id,
            "prompt_chat_id": message.chat_id,
        }
        context.chat_data["time_input_prompt_message_id"] = message.message_id
        context.chat_data["time_input_prompt_chat_id"] = message.chat_id
        return

    if data.startswith("time_hour_up_"):
        _, _, _, _, hours_str, minutes_str = data.split("_")
        hours = (int(hours_str) + 1) % 24
        minutes = int(minutes_str)

    elif data.startswith("time_hour_down_"):
        _, _, _, _, hours_str, minutes_str = data.split("_")
        hours = (int(hours_str) - 1) % 24
        minutes = int(minutes_str)

    elif data.startswith("time_minute_up_"):
        _, _, _, _, hours_str, minutes_str = data.split("_")
        hours = int(hours_str)
        minutes = (int(minutes_str) + 10) % 60

    elif data.startswith("time_minute_down_"):
        _, _, _, _, hours_str, minutes_str = data.split("_")
        hours = int(hours_str)
        minutes = (int(minutes_str) - 10) % 60

    selected_time = time(hours, minutes)
    time_type = ""
    if event:
        if "start" in data:
            event.start_time = selected_time
            time_type = "start"
        elif "stop" in data:
            event.stop_time = selected_time
            time_type = "stop"

        context.chat_data["event"] = event

    logger.info(f"*** time picker: {event}")

    # Обновляем клавиатуру с новым временем
    reply_markup = generate_time_selector(hours=hours, minutes=minutes, time_type=time_type)

    await query.edit_message_reply_markup(reply_markup=reply_markup)


def get_event_constructor(
    event: Event,
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
    locale: str | None = None,
    has_participants: bool = False,
    show_details: bool = False,
    show_back_btn: bool = False,
    back_callback_data: str | None = None,
    read_only: bool = False,
):
    start_time = tr("Начало *", locale)
    stop_time = tr("Окончание", locale)
    description = tr("Описание *", locale)
    recurrent = tr("Повтор", locale)
    participants = tr("Участники", locale)
    show_create_btn = False

    if event:
        if not year:
            year, month, day = event.get_date()

        start_time = event.start_time.strftime("%H:%M") if event.start_time else start_time
        stop_time = event.stop_time.strftime("%H:%M") if event.stop_time else stop_time
        description = format_description(event.description, locale)
        description = description[:20] + "..." if len(str(description)) > 20 else description
        recurrent = f"{recurrent}: {event.recurrent.get_name(locale)}"
        len_participants = len(event.participants) if event.participants else None
        if len_participants:
            participants += f" ({len_participants})"

        if event.start_time and event.description:
            if not event.stop_time or event.stop_time >= event.start_time:
                show_create_btn = True

    formatted_date = format_localized_date(date(int(year), int(month), int(day)), locale=locale, fmt="d MMMM y")
    if show_details:
        date_text = format_localized_date(date(int(year), int(month), int(day)), locale=locale, fmt="d MMMM y")
        start_text = event.start_time.strftime("%H:%M") if event.start_time else "—"
        stop_text = event.stop_time.strftime("%H:%M") if event.stop_time else ""
        description_text = event.description if event.description else "—"
        recurrent_text = event.recurrent.get_name(locale) if event.recurrent else "—"
        participant_names = []
        if event.participants:
            participant_names = [event.all_user_participants.get(tg_id, str(tg_id)) for tg_id in event.participants]
        participants_text = ", ".join(participant_names) if participant_names else "—"
        creator_name = "—"
        if event.creator_tg_id:
            creator_name = event.all_user_participants.get(event.creator_tg_id, str(event.creator_tg_id))
        description_text = format_description(description_text, locale)
        text = (
            tr("📅 Дата: {value}", locale).format(value=date_text) + "\n"
            + tr("⏰ Начало: {value}", locale).format(value=start_text) + "\n"
            + tr("⏳ Окончание: {value}", locale).format(value=stop_text) + "\n"
            + tr("📝 Описание: {value}", locale).format(value=description_text) + "\n"
            + tr("🔁 Повтор: {value}", locale).format(value=recurrent_text) + "\n"
            + tr("👤 Создатель: {value}", locale).format(value=creator_name) + "\n"
            + tr("👥 Участники: {value}", locale).format(value=participants_text) + "\n\n"
            + tr("* - поля обязательные для заполнения", locale)
        )
    else:
        text = tr("✍️ Создать событие на <b>{date}</b> \n\n* - поля обязательные для заполнения", locale).format(date=formatted_date)
    if read_only:
        return text, None

    start_btn = InlineKeyboardButton(text=start_time, callback_data=f"create_event_start_{year}_{month}_{day}")
    stop_btn = InlineKeyboardButton(text=stop_time, callback_data=f"create_event_stop_{year}_{month}_{day}")
    description_btn = InlineKeyboardButton(text=description, callback_data=f"create_event_description_{year}_{month}_{day}")
    emoji_btn = InlineKeyboardButton(text=(event.emoji if event and event.emoji else tr("Эмодзи", locale)), callback_data="emoji_open")
    recurrent_btn = InlineKeyboardButton(text=recurrent, callback_data=f"create_event_recurrent_{year}_{month}_{day}")
    participants_btn = InlineKeyboardButton(text=participants, callback_data=f"create_event_participants_{year}_{month}_{day}")
    buttons = [[start_btn, stop_btn], [emoji_btn], [description_btn], [recurrent_btn], [participants_btn]]

    if show_back_btn:
        callback_data = back_callback_data or "create_event_back_"
        back_btn = InlineKeyboardButton(text=tr("↩ Вернуться в календарь", locale), callback_data=callback_data)
        buttons.append([back_btn])
    elif show_create_btn:
        create_btn = InlineKeyboardButton(text=tr("💾 Сохранить событие", locale), callback_data="create_event_save_to_db")
        buttons.append([create_btn])

    reply_markup = InlineKeyboardMarkup(buttons)

    return text, reply_markup


async def start_event_creation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    year: int,
    month: int,
    day: int,
) -> None:
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")
    context.chat_data.pop("team_participants", None)
    context.chat_data.pop("team_selected", None)
    context.chat_data.pop("participants_status", None)
    context.chat_data.pop("time_picker_message_id", None)
    context.chat_data.pop("time_picker_chat_id", None)
    context.chat_data.pop("await_time_input", None)
    context.chat_data.pop("time_input_prompt_message_id", None)
    context.chat_data.pop("time_input_prompt_chat_id", None)
    context.chat_data.pop("edit_event_id", None)
    context.chat_data.pop("edit_event_original", None)
    context.chat_data.pop("edit_event_readonly", None)

    event = Event(
        event_date=datetime.datetime.strptime(f"{year}-{month:02d}-{day:02d}", "%Y-%m-%d"),
        tg_id=update.effective_chat.id,
        creator_tg_id=update.effective_chat.id,
    )
    context.chat_data["event"] = event

    participants = await db_controller.get_participants_with_status(tg_id=update.effective_chat.id, include_inactive=True)
    context.chat_data["participants_status"] = {tg_id: is_active for tg_id, (_, is_active) in participants.items()}
    context.chat_data["event"].all_user_participants = {tg_id: name for tg_id, (name, _) in participants.items()}

    has_participants = bool(event.all_user_participants)
    text, reply_markup = get_event_constructor(
        event=event,
        year=year,
        month=month,
        day=day,
        locale=locale,
        has_participants=has_participants,
        show_details=bool(context.chat_data.get("edit_event_id")),
    )
    await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")


async def handle_create_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_create_event_callback")
    query = update.callback_query
    await query.answer()
    data = query.data

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")

    event: Event | None = context.chat_data.get("event")
    if not event:
        event = Event(event_date=datetime.datetime.now().date(), tg_id=update.effective_chat.id, creator_tg_id=update.effective_chat.id)
        context.chat_data["event"] = event
    elif not event.creator_tg_id:
        event.creator_tg_id = update.effective_chat.id
        context.chat_data["event"] = event
    if context.chat_data.get("edit_event_readonly") and not data.startswith("create_event_back_"):
        await query.answer(tr("Только просмотр", locale), show_alert=False)
        return

    year, month, day = event.get_date()

    logger.info(f"* EVENT: {event}")

    if data.startswith("create_event_begin_"):
        parts = data.split("_")
        if len(parts) >= 6:
            year, month, day = parts[3], parts[4], parts[5]
            await start_event_creation(
                update=update,
                context=context,
                year=int(year),
                month=int(month),
                day=int(day),
            )
        else:
            if not event:
                event = Event(event_date=datetime.datetime.now().date(), tg_id=update.effective_chat.id)
                context.chat_data["event"] = event
            year, month, day = event.get_date()
            has_participants = bool(event.all_user_participants)
            show_back_btn, back_callback_data = _get_back_button_state(context, event, year, month, day)
            text, reply_markup = get_event_constructor(
                event=event,
                year=year,
                month=month,
                day=day,
                locale=locale,
                has_participants=has_participants,
                show_details=bool(context.chat_data.get("edit_event_id")),
                show_back_btn=show_back_btn,
                back_callback_data=back_callback_data,
            )
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    elif data.startswith("create_event_start_"):
        hours = 12
        minutes = 0
        if event and event.start_time:
            hours = event.start_time.hour
            minutes = event.start_time.minute
        elif event and not event.start_time:
            event.start_time = datetime.datetime.strptime("12:00", "%H:%M").time()
            context.chat_data["event"] = event

        reply_markup = generate_time_selector(hours=int(hours), minutes=int(minutes), time_type="start")

        await query.edit_message_text(text=tr("Укажите время начала события", locale), reply_markup=reply_markup)

    elif data.startswith("create_event_stop_"):
        text = tr("Укажите время окончания события", locale)
        hours = 12
        minutes = 0
        if event and event.stop_time:
            hours = event.stop_time.hour
            minutes = event.stop_time.minute
        elif event and event.start_time:
            hours = event.start_time.hour
            minutes = event.start_time.minute
            hours = int(hours)
            minutes = int(minutes)
            event.stop_time = datetime.datetime.strptime(f"{hours:02d}:{minutes:02d}", "%H:%M").time()
            context.chat_data["event"] = event
            text += tr("\n\n (Время начала события: {time})", locale).format(time=f"{hours:02d}:{minutes:02d}")
        elif event and not event.stop_time:
            event.stop_time = datetime.datetime.strptime("12:00", "%H:%M").time()
            context.chat_data["event"] = event
        reply_markup = generate_time_selector(hours=int(hours), minutes=int(minutes), time_type="stop")
        await query.edit_message_text(text=text, reply_markup=reply_markup)

    elif data.startswith("create_event_description_"):
        target_message_id = None
        target_chat_id = None
        if query.message:
            target_message_id = getattr(query.message, "message_id", None) or getattr(query.message, "id", None)
            target_chat_id = getattr(query.message, "chat_id", None)
        if target_chat_id is None and update.effective_chat:
            target_chat_id = update.effective_chat.id
        prompt_message_id = None
        prompt_chat_id = None
        if query.message:
            message = await query.message.reply_text(text=tr("Опиши, что будет в событии:", locale))
            if message:
                prompt_message_id = getattr(message, "message_id", None) or getattr(message, "id", None)
                prompt_chat_id = getattr(message, "chat_id", None)
        elif update.effective_chat:
            message = await context.bot.send_message(chat_id=update.effective_chat.id, text=tr("Опиши, что будет в событии:", locale))
            if message:
                prompt_message_id = getattr(message, "message_id", None) or getattr(message, "id", None)
                prompt_chat_id = getattr(message, "chat_id", None)
        context.chat_data["await_event_description"] = {
            "message_id": target_message_id,
            "chat_id": target_chat_id,
            "prompt_message_id": prompt_message_id,
            "prompt_chat_id": prompt_chat_id,
        }

    elif data.startswith("create_event_save_recurrent_"):
        _, _, _, _, recurrent = data.split("_")
        event.recurrent = Recurrent(recurrent)
        context.chat_data["event"] = event

        has_participants = bool(event.all_user_participants)
        show_back_btn, back_callback_data = _get_back_button_state(context, event, year, month, day)
        text, reply_markup = get_event_constructor(
            event=event,
            year=year,
            month=month,
            day=day,
            locale=locale,
            has_participants=has_participants,
            show_details=bool(context.chat_data.get("edit_event_id")),
            show_back_btn=show_back_btn,
            back_callback_data=back_callback_data,
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    elif data.startswith("create_event_recurrent_"):
        list_btn = []
        for item in Recurrent.get_all_names(locale):
            list_btn.append([InlineKeyboardButton(item[0], callback_data=f"create_event_save_recurrent_{item[1]}")])

        reply_markup = InlineKeyboardMarkup(list_btn)
        await query.edit_message_text(text=tr("Как часто повторять событие:", locale), reply_markup=reply_markup)

    elif data.startswith("create_event_participants_"):
        list_btn = []
        if event.all_user_participants:
            for tg_id, name in event.all_user_participants.items():
                is_active = context.chat_data.get("participants_status", {}).get(tg_id, True)
                if not is_active:
                    name = f"{name} ({tr('не в боте', locale)})"
                elif tg_id in event.participants:
                    name = f"{name} ✅"
                list_btn.append([InlineKeyboardButton(name, callback_data=f"participants_{tg_id}")])

        list_btn.append([InlineKeyboardButton("✅ OK", callback_data="create_event_begin_")])

        reply_markup = InlineKeyboardMarkup(list_btn)
        await query.edit_message_text(
            text=tr("Добавь пользователя: нажми 📎скрепку ➡️ 👤Контакт ➡️ выбери участника события ➡️ Отправить контакт", locale),
            reply_markup=reply_markup,
        )
    elif data.startswith("create_event_back_"):
        parts = data.split("_")
        if len(parts) >= 6:
            year, month, day = int(parts[3]), int(parts[4]), int(parts[5])
        else:
            year, month, day = event.get_date()

        context.chat_data.pop("team_participants", None)
        context.chat_data.pop("team_selected", None)
        context.chat_data.pop("event", None)
        context.chat_data.pop("participants_status", None)
        context.chat_data.pop("time_picker_message_id", None)
        context.chat_data.pop("time_picker_chat_id", None)
        context.chat_data.pop("await_time_input", None)
        context.chat_data.pop("time_input_prompt_message_id", None)
        context.chat_data.pop("time_input_prompt_chat_id", None)
        context.chat_data.pop("edit_event_id", None)
        context.chat_data.pop("edit_event_original", None)
        context.chat_data.pop("edit_event_readonly", None)

        from handlers.cal import build_day_view  # local import to avoid circular dependency

        text, reply_markup = await build_day_view(
            user_id=user.id,
            year=year,
            month=month,
            day=day,
            tz_name=db_user.time_zone,
            locale=locale,
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    elif data.startswith("create_event_save_to_db"):
        edit_event_id = context.chat_data.pop("edit_event_id", None)
        context.chat_data.pop("edit_event_original", None)
        context.chat_data.pop("edit_event_readonly", None)
        if edit_event_id:
            event_id = await db_controller.update_event(event_id=edit_event_id, event=event, tz_name=db_user.time_zone)
        else:
            event_id = await db_controller.save_event(event=event, tz_name=db_user.time_zone)

        await db_controller.set_event_participants(event_id=event_id, participant_ids=event.participants)

        context.chat_data.pop("team_participants", None)
        context.chat_data.pop("team_selected", None)
        context.chat_data.pop("event", None)
        context.chat_data.pop("participants_status", None)
        context.chat_data.pop("time_picker_message_id", None)
        context.chat_data.pop("time_picker_chat_id", None)
        context.chat_data.pop("await_time_input", None)
        context.chat_data.pop("time_input_prompt_message_id", None)
        context.chat_data.pop("time_input_prompt_chat_id", None)

        year, month, day = event.get_date()
        from handlers.cal import build_day_view  # local import to avoid circular dependency

        text, reply_markup = await build_day_view(
            user_id=user.id,
            year=year,
            month=month,
            day=day,
            tz_name=db_user.time_zone,
            locale=locale,
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

        if event.participants:
            bot = telegram.Bot(token=TOKEN)
            creator_name = str(update.effective_chat.first_name).title()
            date_text = f"{event.event_date.day}.{event.event_date.month:02d}.{event.event_date.year}"
            time_range = (
                f"{event.start_time.strftime('%H:%M')}"
                f"{'-' + event.stop_time.strftime('%H:%M') if event.stop_time else ''}"
            )
            for participant_id in event.participants:
                recipient_locale = await resolve_user_locale(participant_id, platform="tg")
                text = (
                    tr("{creator} добавил событие", recipient_locale).format(creator=creator_name)
                    + "\n"
                    + tr("Дата: {date}", recipient_locale).format(date=date_text)
                    + "\n"
                    + tr("Время: {start}", recipient_locale).format(start=time_range)
                    + "\n"
                    + tr("Описание: {description}", recipient_locale).format(description=event.description)
                )

                new_event_id = await db_controller.resave_event_to_participant(event_id=event_id, user_id=participant_id)
                if new_event_id:
                    await db_controller.set_event_participants(event_id=new_event_id, participant_ids=event.participants)
                creator_id = update.effective_chat.id if update.effective_chat else None
                cancel_data = f"create_participant_event_cancel_{new_event_id}"
                if creator_id:
                    cancel_data = f"{cancel_data}_{creator_id}"
                btn = [[InlineKeyboardButton(tr("Не добавлять", recipient_locale), callback_data=cancel_data)]]
                reply_markup = InlineKeyboardMarkup(btn)
                await bot.send_message(chat_id=participant_id, text=text, reply_markup=reply_markup)


async def handle_edit_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_edit_event_callback")
    query = update.callback_query
    await query.answer()

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")

    parts = query.data.split("_")
    event_id = int(parts[-1])

    event = await db_controller.get_event_by_id(event_id=event_id, tz_name=db_user.time_zone)
    if not event:
        await query.edit_message_text(text=tr("Событие не найдено", locale))
        return

    event.participants = await db_controller.get_event_participants(event_id=event_id)

    context.chat_data["event"] = event
    context.chat_data["edit_event_id"] = event_id
    context.chat_data["edit_event_original"] = _event_snapshot(event)

    participants = await db_controller.get_participants_with_status(tg_id=user.id, include_inactive=True)
    context.chat_data["participants_status"] = {tg_id: is_active for tg_id, (_, is_active) in participants.items()}
    event.all_user_participants = {tg_id: name for tg_id, (name, _) in participants.items()}
    missing_names = [tg_id for tg_id in (event.participants or []) if tg_id not in event.all_user_participants]
    if event.creator_tg_id and event.creator_tg_id not in event.all_user_participants:
        missing_names.append(event.creator_tg_id)
    if missing_names:
        event.all_user_participants.update(await db_controller.get_users_short_names(missing_names))

    year, month, day = event.get_date()
    has_participants = bool(event.all_user_participants)
    if event.creator_tg_id and event.creator_tg_id != user.id:
        context.chat_data["edit_event_readonly"] = True
        text, _ = get_event_constructor(
            event=event,
            year=year,
            month=month,
            day=day,
            locale=locale,
            has_participants=has_participants,
            show_details=True,
            read_only=True,
        )
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(tr("↩ Вернуться в календарь", locale), callback_data=f"create_event_back_{year}_{month}_{day}")]]
        )
    else:
        context.chat_data.pop("edit_event_readonly", None)
        show_back_btn, back_callback_data = _get_back_button_state(context, event, year, month, day)
        text, reply_markup = get_event_constructor(
            event=event,
            year=year,
            month=month,
            day=day,
            locale=locale,
            has_participants=has_participants,
            show_details=bool(context.chat_data.get("edit_event_id")),
            show_back_btn=show_back_btn,
            back_callback_data=back_callback_data,
        )
    await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")


async def show_upcoming_events(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("show_upcoming_events")

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")

    events = await db_controller.get_nearest_events(user_id=user.id, tz_name=db_user.time_zone)

    if events:
        list_events = [tr("Ближайшие события:", locale)]
        for _event in events:
            event_dt = list(_event.keys())[0]
            value = list(_event.values())[0]
            description = value[0] if isinstance(value, tuple) else value
            emoji = value[1] if isinstance(value, tuple) else None
            date_part = event_dt.strftime('%d-%m-%Y')
            time_part = event_dt.strftime('%H:%M')
            emoji_part = f" {emoji}" if emoji else ""
            list_events.append(f"<b>{date_part}{emoji_part} {time_part}</b> - {description}")
        text = "\n".join(list_events)
    else:
        text = tr("Ближайшие события не найдены", locale)

    await update.message.reply_text(text, parse_mode="HTML")


async def handle_delete_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_delete_event_callback")
    query = update.callback_query
    await query.answer()

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")
    # user_id = update.effective_chat.id
    data = query.data

    if "_id_" in data:
        _, _, _, db_id, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)

        await db_controller.delete_event_by_id(event_id=db_id, tz_name=db_user.time_zone)

        from handlers.cal import build_day_view  # local import to avoid circular dependency

        text, reply_markup = await build_day_view(
            user_id=user.id,
            year=year,
            month=month,
            day=day,
            tz_name=db_user.time_zone,
            locale=locale,
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return
        formatted_date = f"{day:02d}.{month:02d}.{year}"

        header = "Удалено одно событие"
        no_events = "Нет событий"

        if events:
            text = f"{header}\n\n<b>{formatted_date}</b>\n{events}"
        else:
            text = f"{header}\n\n<b>{formatted_date}</b>\n{no_events}"

        from handlers.cal import generate_calendar  # local import to avoid circular dependency

        calendar_markup = await generate_calendar(year=year, month=month, user_id=user.id, tz_name=db_user.time_zone)
        action_row = [
            InlineKeyboardButton(
            )
        ]
        delete_row = []
        if events:
            delete_row.append(InlineKeyboardButton(tr("🗑 Удалить событие", locale), callback_data=f"delete_event_{year}_{month}_{day}"))
        reply_markup = InlineKeyboardMarkup(list(calendar_markup.inline_keyboard) + [action_row] + [delete_row])
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return

    elif "_recurDay_" in data:
        _, _, _, db_id, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        await db_controller.create_cancel_event(event_id=int(db_id), cancel_date=date.fromisoformat(f"{year}-{month:02d}-{day:02d}"))

        from handlers.cal import build_day_view  # local import to avoid circular dependency

        text, reply_markup = await build_day_view(
            user_id=user.id,
            year=year,
            month=month,
            day=day,
            tz_name=db_user.time_zone,
            locale=locale,
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
        return
        formatted_date = f"{day:02d}.{month:02d}.{year}"

        header = "Удалено одно событие"
        no_events = "Нет событий"

        if events:
            text = f"{header}\n\n<b>{formatted_date}</b>\n{events}"
        else:
            text = f"{header}\n\n<b>{formatted_date}</b>\n{no_events}"

        from handlers.cal import generate_calendar  # local import to avoid circular dependency

        calendar_markup = await generate_calendar(year=year, month=month, user_id=user.id, tz_name=db_user.time_zone)
        action_row = [
            InlineKeyboardButton(
            )
        ]
        delete_row = []
        if events:
            delete_row.append(InlineKeyboardButton(tr("🗑 Удалить событие", locale), callback_data=f"delete_event_{year}_{month}_{day}"))
        reply_markup = InlineKeyboardMarkup(list(calendar_markup.inline_keyboard) + [action_row] + [delete_row])
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    elif "_recurrent_" in data:
        _, _, _, db_id, year, month, day = data.split("_")
        formatted_date = format_localized_date(
            date(int(year), int(month), int(day)),
            locale=locale,
            fmt="d MMMM y",
        )

        text = tr(
            "Событие повторяющееся.\nОтмените событие на дату {formatted_date} или удалите его полностью",
            locale,
        ).format(formatted_date=formatted_date)
        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        tr("🗑 Удалить на дату {date}", locale).format(date=formatted_date),
                        callback_data=f"delete_event_recurDay_{db_id}_{year}_{month}_{day}",
                    )
                ],
                [InlineKeyboardButton(tr("🗑 Удалить полностью", locale), callback_data=f"delete_event_id_{db_id}_{year}_{month}_{day}")],
                [InlineKeyboardButton(tr("Отмена", locale), callback_data=f"cal_select_{year}_{month}_{day}")],
            ]
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

        ...
    elif data.startswith("delete_event_select_"):
        _, _, _, event_id_str, year_str, month_str, day_str = data.split("_")
        event_id = int(event_id_str)
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)

        selected_ids = set(context.chat_data.get("delete_selected_ids") or [])
        if event_id in selected_ids:
            selected_ids.remove(event_id)
        else:
            selected_ids.add(event_id)

        context.chat_data["delete_selected_ids"] = list(selected_ids)

        events = await db_controller.get_current_day_events_by_user(
            user_id=user.id, month=month, year=year, day=day, deleted=True, tz_name=db_user.time_zone
        )
        formatted_date = format_localized_date(date(year, month, day), locale=locale, fmt="d MMMM y")
        text = f"<b>{formatted_date}</b>\n{tr('Выберете события для удаления:', locale)}"
        reply_markup = _build_delete_events_markup(events, selected_ids, year, month, day, locale=locale)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    elif data.startswith("delete_event_confirm_"):
        _, _, _, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)
        selected_ids = set(context.chat_data.get("delete_selected_ids") or [])
        if selected_ids:
            for event_id in selected_ids:
                await db_controller.delete_event_by_id(event_id=event_id, tz_name=db_user.time_zone)
        context.chat_data.pop("delete_selected_ids", None)

        from handlers.cal import build_day_view  # local import to avoid circular dependency

        text, reply_markup = await build_day_view(
            user_id=user.id,
            year=year,
            month=month,
            day=day,
            tz_name=db_user.time_zone,
            locale=locale,
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    else:  # конструктор событий для удаления
        _, _, year, month, day = data.split("_")
        year = int(year)
        month = int(month)
        day = int(day)

        context.chat_data["delete_selected_ids"] = []
        events = await db_controller.get_current_day_events_by_user(
            user_id=user.id, month=month, year=year, day=day, deleted=True, tz_name=db_user.time_zone
        )

        formatted_date = format_localized_date(date(year, month, day), locale=locale, fmt="d MMMM y")
        text = f"<b>{formatted_date}</b>\n{tr('Выберете события для удаления:', locale)}"
        reply_markup = _build_delete_events_markup(events, set(), year, month, day, locale=locale)
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")


async def handle_event_participants_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_event_participants_callback")
    query = update.callback_query
    data = query.data

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")

    if "cancel" in data:
        parts = data.split("_")
        event_id = parts[4]
        creator_id = None
        if len(parts) > 5:
            try:
                creator_id = int(parts[5])
            except ValueError:
                creator_id = None

        _, event_info = await db_controller.delete_event_by_id(event_id=event_id, tz_name=db_user.time_zone)
        await query.edit_message_text(text=tr("Событие не добавлено в календарь.", locale))

        if creator_id and update.effective_chat and creator_id != update.effective_chat.id:
            creator_locale = await resolve_user_locale(creator_id, platform="tg")
            user_name = update.effective_chat.full_name or update.effective_chat.first_name or tr("Участник", creator_locale)
            text = tr("Участник {user_name} отказался от участия в событии: {event_info}", creator_locale).format(
                user_name=user_name,
                event_info=event_info,
            )
            try:
                await context.bot.send_message(chat_id=creator_id, text=text)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to notify event creator about отказ")
        return


async def handle_reschedule_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_reschedule_event_callback")

    query = update.callback_query
    await query.answer()
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")

    parts = query.data.split("_")
    if len(parts) < 4:
        return

    event_id = parts[2]
    action = parts[3]

    shift_hours = 0
    shift_days = 0
    if action == "hour":
        shift_hours = 1
        human = tr("на 1 час", locale)
    elif action == "day":
        shift_days = 1
        human = tr("на завтра", locale)
    else:
        return

    new_event_id = await db_controller.reschedule_event(event_id=event_id, shift_hours=shift_hours, shift_days=shift_days)
    if not new_event_id:
        await query.edit_message_text(text=tr("Не удалось перенести событие.", locale))
        return

    await query.edit_message_text(text=tr("Событие перенесено {human}.", locale).format(human=human))
