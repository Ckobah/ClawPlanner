import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

import config
from database.db_controller import db_controller
from entities import TgUser
from i18n import format_localized_date, month_year_label, resolve_user_locale, tr, weekday_labels

logger = logging.getLogger(__name__)


def to_superscript(number: int) -> str:
    superscript_map = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
    return str(number).translate(superscript_map)


async def generate_calendar(
    user_id: int,
    year: int,
    month: int,
    tz_name: str = config.DEFAULT_TIMEZONE_NAME,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    event_dict = await db_controller.get_current_month_events_by_user(user_id=user_id, month=month, year=year, tz_name=tz_name)

    first_weekday, num_days = monthrange(year, month)

    header = month_year_label(year=year, month=month, locale=locale)

    keyboard = []

    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1

    keyboard.append(
        [
            InlineKeyboardButton("◀", callback_data=f"cal_nav_{prev_year}_{prev_month}"),
            InlineKeyboardButton(header, callback_data=f"cal_month_{year}_{month}"),
            InlineKeyboardButton("▶", callback_data=f"cal_nav_{next_year}_{next_month}"),
        ]
    )

    keyboard.append([InlineKeyboardButton(day, callback_data="cal_ignore") for day in weekday_labels(locale)])

    week = []

    for _ in range(first_weekday):
        week.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))

    for day in range(1, num_days + 1):
        number_events = event_dict.get(day)
        show_day = f"{day}{to_superscript(number_events)}" if number_events else day
        week.append(InlineKeyboardButton(str(show_day), callback_data=f"cal_select_{year}_{month}_{day}"))

        if len(week) == 7:
            keyboard.append(week)
            week = []

    if week:
        for _ in range(7 - len(week)):
            week.append(InlineKeyboardButton(" ", callback_data="cal_ignore"))
        keyboard.append(week)

    return InlineKeyboardMarkup(keyboard)


async def generate_week_calendar(
    user_id: int,
    year: int,
    month: int,
    day: int,
    tz_name: str = config.DEFAULT_TIMEZONE_NAME,
    locale: str | None = None,
) -> InlineKeyboardMarkup:
    ref_date = date(year, month, day)
    week_start = ref_date - timedelta(days=ref_date.weekday())
    week_dates = [week_start + timedelta(days=i) for i in range(7)]

    event_dicts: dict[tuple[int, int], dict[int, int]] = {}
    for day_date in week_dates:
        key = (day_date.year, day_date.month)
        if key not in event_dicts:
            event_dicts[key] = await db_controller.get_current_month_events_by_user(
                user_id=user_id, month=day_date.month, year=day_date.year, tz_name=tz_name
            )

    header = month_year_label(year=ref_date.year, month=ref_date.month, locale=locale)

    prev_week = ref_date - timedelta(days=7)
    next_week = ref_date + timedelta(days=7)

    keyboard = []
    keyboard.append(
        [
            InlineKeyboardButton("◀", callback_data=f"cal_week_nav_{prev_week.year}_{prev_week.month}_{prev_week.day}"),
            InlineKeyboardButton(header, callback_data=f"cal_month_{ref_date.year}_{ref_date.month}"),
            InlineKeyboardButton("▶", callback_data=f"cal_week_nav_{next_week.year}_{next_week.month}_{next_week.day}"),
        ]
    )

    weekdays = weekday_labels(locale)
    keyboard.append([InlineKeyboardButton(day, callback_data="cal_ignore") for day in weekdays])

    week_row = []
    for day_date in week_dates:
        event_dict = event_dicts[(day_date.year, day_date.month)]
        number_events = event_dict.get(day_date.day)
        show_day = f"{day_date.day}{to_superscript(number_events)}" if number_events else day_date.day
        week_row.append(InlineKeyboardButton(str(show_day), callback_data=f"cal_select_{day_date.year}_{day_date.month}_{day_date.day}"))
    keyboard.append(week_row)

    return InlineKeyboardMarkup(keyboard)


async def show_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("show_calendar")

    context.chat_data.pop("team_participants", None)
    context.chat_data.pop("team_selected", None)
    context.chat_data.pop("event", None)
    context.chat_data.pop("participants_status", None)
    context.chat_data.pop("time_picker_message_id", None)
    context.chat_data.pop("time_picker_chat_id", None)
    context.chat_data.pop("await_time_input", None)
    context.chat_data.pop("time_input_prompt_message_id", None)
    context.chat_data.pop("time_input_prompt_chat_id", None)

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")

    # user_tz = timezone(timedelta(hours=3))
    tz_name = db_user.time_zone if db_user.time_zone else config.DEFAULT_TIMEZONE_NAME
    today = datetime.now(tz=ZoneInfo(tz_name))

    reply_markup = await generate_calendar(year=today.year, month=today.month, user_id=user.id, tz_name=db_user.time_zone, locale=locale)

    keyboard = list(reply_markup.inline_keyboard)
    keyboard.append(
        [
            InlineKeyboardButton(
                tr("✍️ Создать событие на {date}", locale).format(date=f"{today.day:02d}.{today.month:02d}.{today.year}"),
                callback_data=f"create_event_begin_{today.year}_{today.month}_{today.day}",
            )
        ]
    )

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        tr("📅 Выберите дату события:", locale),
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


async def build_day_view(
    user_id: int,
    year: int,
    month: int,
    day: int,
    tz_name: str,
    locale: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    events = await db_controller.get_current_day_events_by_user(user_id=user_id, month=month, year=year, day=day, tz_name=tz_name)
    events_list = await db_controller.get_current_day_events_by_user(
        user_id=user_id, month=month, year=year, day=day, tz_name=tz_name, deleted=True
    )

    reply_btn_create = InlineKeyboardButton(
        tr("✍️ Создать событие на {date}", locale).format(date=f"{day:02d}.{month:02d}.{year}"),
        callback_data=f"create_event_begin_{year}_{month}_{day}",
    )
    reply_btn_delete = InlineKeyboardButton(tr("🗑 Удалить событие", locale), callback_data=f"delete_event_{year}_{month}_{day}")
    action_row = [reply_btn_create]
    formatted_date = format_localized_date(date(year, month, day), locale=locale, fmt="d MMMM y")

    delete_row = []
    event_buttons = []
    if events:
        delete_row.append(reply_btn_delete)
        for ev_text, ev_id, _ in events_list:
            btn_text = str(ev_text).replace("\n", " - ").strip()
            if btn_text:
                event_buttons.append([InlineKeyboardButton(btn_text, callback_data=f"edit_event_{ev_id}")])
        text = tr("События на <b>{date}</b>:", locale).format(date=formatted_date)
    else:
        text = tr("Вы выбрали дату: <b>{date}</b>", locale).format(date=formatted_date)

    calendar_markup = await generate_week_calendar(year=year, month=month, day=day, user_id=user_id, tz_name=tz_name, locale=locale)
    reply_markup = InlineKeyboardMarkup(list(calendar_markup.inline_keyboard) + event_buttons + [action_row] + [delete_row])
    return text, reply_markup


async def handle_calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_calendar_callback")
    query = update.callback_query
    try:
        await query.answer()
    except BadRequest as exc:
        if "Query is too old" in str(exc) or "query id is invalid" in str(exc):
            logger.info("Skip expired callback query")
        else:
            raise

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="tg", preferred_language_code=tg_user.language_code)
    logger.info(f"*** DB user: {db_user}")

    data = query.data

    if data.startswith("cal_nav_"):
        _, _, year_str, month_str = data.split("_")
        year = int(year_str)
        month = int(month_str)

        # Генерируем новый календарь
        reply_markup = await generate_calendar(year=year, month=month, user_id=user.id, tz_name=db_user.time_zone, locale=locale)
        await query.edit_message_text(tr("📅 Выберите дату события:", locale), reply_markup=reply_markup)

    elif data.startswith("cal_week_nav_"):
        parts = data.split("_")
        year = int(parts[-3])
        month = int(parts[-2])
        day = int(parts[-1])

        reply_markup = await generate_week_calendar(
            year=year,
            month=month,
            day=day,
            user_id=user.id,
            tz_name=db_user.time_zone,
            locale=locale,
        )
        await query.edit_message_text(tr("📅 Выберите дату события:", locale), reply_markup=reply_markup)

    elif data.startswith("cal_month_"):
        _, _, year_str, month_str = data.split("_")
        year = int(year_str)
        month = int(month_str)

        reply_markup = await generate_calendar(year=year, month=month, user_id=user.id, tz_name=db_user.time_zone, locale=locale)
        await query.edit_message_text(tr("📅 Выберите дату события:", locale), reply_markup=reply_markup)

    elif data.startswith("cal_select_"):
        logger.info("Выбор события cal_select_")
        _, _, year_str, month_str, day_str = data.split("_")
        year = int(year_str)
        month = int(month_str)
        day = int(day_str)

        events = await db_controller.get_current_day_events_by_user(
            user_id=user.id, month=month, year=year, day=day, tz_name=db_user.time_zone
        )
        if not events:
            from handlers.events import start_event_creation  # local import to avoid circular dependency

            await start_event_creation(update=update, context=context, year=year, month=month, day=day)
            return

        text, reply_markup = await build_day_view(
            user_id=user.id,
            year=year,
            month=month,
            day=day,
            tz_name=db_user.time_zone,
            locale=locale,
        )
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

    elif data == "cal_ignore":
        pass
