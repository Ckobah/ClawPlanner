import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from max_bot.compat import KeyboardButton, ReplyKeyboardMarkup
from max_bot.context import MaxContext, MaxMessage, MaxUpdate
from timezonefinder import TimezoneFinder

from database.db_controller import db_controller
from entities import MaxUser
from i18n import normalize_locale, resolve_user_locale, tr
from max_bot.handlers.cal import show_calendar

SKIP_LOCATION_TEXT = "⏭ Пропустить"
SHARE_LOCATION_TEXT = "📍 Поделиться геолокацией"
MAIN_MENU_CALENDAR_TEXT = "📅 Показать календарь"
MAIN_MENU_UPCOMING_TEXT = "🗓 Ближайшие события"
MAIN_MENU_NOTES_TEXT = "📝 Заметки"

logger = logging.getLogger(__name__)


async def start(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("start")
    context.chat_data.pop("team_participants", None)
    context.chat_data.pop("team_selected", None)
    context.chat_data.pop("event", None)
    context.chat_data.pop("participants_status", None)
    context.chat_data.pop("time_picker_message_id", None)
    context.chat_data.pop("time_picker_chat_id", None)
    context.chat_data.pop("await_time_input", None)
    context.chat_data.pop("time_input_prompt_message_id", None)
    context.chat_data.pop("time_input_prompt_chat_id", None)
    context.chat_data.pop("await_note_create", None)
    context.chat_data.pop("await_note_edit", None)

    user = update.effective_chat
    tg_user = MaxUser.model_validate(user)
    db_user = await db_controller.save_update_max_user(max_user=tg_user)
    locale = await resolve_user_locale(user.id, platform="max", preferred_language_code=tg_user.language_code)
    await db_controller.set_user_language(user_id=user.id, language_code=normalize_locale(locale), platform="max")

    logger.info(f"*** DB user: {db_user}")

    keyboard = [[KeyboardButton(SKIP_LOCATION_TEXT)]]

    if update.effective_chat.type == "private":
        keyboard.insert(0, [KeyboardButton(SHARE_LOCATION_TEXT, request_location=True)])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        tr(
            "Привет, {name}!\nДля получения событий по твоему часовому поясу, тебе нужно поделиться геолокацией. Если ты живешь по Москоскому времени, то можешь нажать «Пропустить».",
            locale,
        ).format(name=user.first_name),
        reply_markup=reply_markup,
        include_menu=False,
    )


async def handle_help(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("handle_help")
    context.chat_data.pop("team_participants", None)
    context.chat_data.pop("team_selected", None)
    context.chat_data.pop("event", None)
    context.chat_data.pop("participants_status", None)
    context.chat_data.pop("time_picker_message_id", None)
    context.chat_data.pop("time_picker_chat_id", None)
    context.chat_data.pop("await_time_input", None)
    context.chat_data.pop("time_input_prompt_message_id", None)
    context.chat_data.pop("time_input_prompt_chat_id", None)
    context.chat_data.pop("await_note_create", None)
    context.chat_data.pop("await_note_edit", None)
    text = (
        "👋 Привет! Я помогу планировать дела и напоминать о событиях.\n\n"
        "📌 Основные команды:\n"
        "• /start — запуск бота\n"
        "• /team — управление участниками (удаление лишних)\n"
        "• /help — это сообщение\n\n"
        "🗓️ Календарь и события:\n"
        "1) Открой «Календарь» и выбери дату.\n"
        "2) Нажми «✍️Создать событие».\n"
        "3) Укажи время начала/окончания и описание.\n"
        "4) При необходимости выбери повторения.\n"
        "5) Добавь участников и нажми «Сохранить событие».\n\n"
        "👥 Участники:\n"
        "• Чтобы добавить участника, отправь его контакт в чат.\n"
        "• Если человек еще не запускал бота — он появится с пометкой «не в боте».\n"
        "• Управление списком участников — команда /team.\n\n"
        "⏰ Ближайшие события:\n"
        "Нажми «Ближайшие события», чтобы увидеть список на несколько дней вперед.\n\n"
        "🗑️ Удаление событий:\n"
        "В календаре выбери дату и нажми «Удалить событие».\n\n"
        "Если что-то не работает — просто напиши @FamPlanner, помогу разобраться 😊"
    )
    await update.message.reply_text(text=text)


async def handle_location(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("handle_location")

    location = update.message.location
    lat = location.get("latitude") if isinstance(location, dict) else None
    lng = location.get("longitude") if isinstance(location, dict) else None

    user = update.effective_chat
    tg_user = MaxUser.model_validate(user)
    db_user = await db_controller.save_update_max_user(max_user=tg_user)
    logger.info(f"*** DB user: {db_user}")

    logger.info(
        f"Location update from {user.id} ({user.first_name}): lat={lat}, lng={lng}"
    )
    if lat is None or lng is None:
        await update.message.reply_text("Could not read location. Please try again.")
        return

    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lng)
    logger.info(f"tz name; {tz_name}")
    try:
        now = datetime.now(ZoneInfo(tz_name))
        offset = now.utcoffset()

        tg_user.time_zone = tz_name
        await db_controller.save_update_max_user(max_user=tg_user)
        logger.info(f"OFFSET: {offset}, {int(offset.total_seconds()/3600)}, {type(offset)}")
    except:  # noqa
        logger.exception("OFFSET ERR: " )
        pass

    await show_calendar(update, context)


async def handle_skip(update: MaxUpdate, context: MaxContext) -> None:
    logger.info("handle_skip")

    user = update.effective_user
    logger.info(f"Пользователь {user.id} ({user.first_name}) пропустил геолокацию")

    await show_calendar(update, context)


async def show_main_menu_keyboard(message: MaxMessage) -> None:
    locale = await resolve_user_locale(getattr(message, "chat_id", None), platform="max")
    keyboard = [[KeyboardButton(MAIN_MENU_CALENDAR_TEXT)], [KeyboardButton(MAIN_MENU_UPCOMING_TEXT)], [KeyboardButton(MAIN_MENU_NOTES_TEXT)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await message.reply_text(tr("Меню:", locale), reply_markup=reply_markup)


async def show_main_menu(message: MaxMessage, add_text: str | None = None) -> None:
    logger.info("show_main_menu")

    locale = await resolve_user_locale(getattr(message, "chat_id", None), platform="max")
    keyboard = [[KeyboardButton(MAIN_MENU_CALENDAR_TEXT)], [KeyboardButton(MAIN_MENU_UPCOMING_TEXT)], [KeyboardButton(MAIN_MENU_NOTES_TEXT)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    text = f"{add_text}\n\n{tr('Выберите действие:', locale)}" if add_text else tr("Выберите действие:", locale)

    await message.reply_text(text=text, reply_markup=reply_markup)
