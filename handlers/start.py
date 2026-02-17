import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import BotCommand, BotCommandScopeChat, KeyboardButton, Message, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes
from timezonefinder import TimezoneFinder

from database.db_controller import db_controller
from entities import TgUser
from handlers.cal import show_calendar
from i18n import normalize_locale, resolve_user_locale, tr
from weather import weather_service

logger = logging.getLogger(__name__)


def _commands_for_locale(locale: str) -> list[BotCommand]:
    if locale == "en":
        return [
            BotCommand("start", "Start bot"),
            BotCommand("my_id", "Show my Telegram ID"),
            BotCommand("team", "Manage participants"),
            BotCommand("help", "Help"),
            BotCommand("language", "Change language"),
        ]
    return [
        BotCommand("start", "Запустить бота"),
        BotCommand("my_id", "Показать мой Telegram ID"),
        BotCommand("team", "Управление участниками"),
        BotCommand("help", "Помощь"),
        BotCommand("language", "Сменить язык"),
    ]


async def _set_chat_commands(context: ContextTypes.DEFAULT_TYPE, chat_id: int, locale: str) -> None:
    if not getattr(context, "bot", None):
        return
    await context.bot.set_my_commands(
        _commands_for_locale(locale),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    db_locale_raw = getattr(db_user, "language_code", None)
    db_locale = normalize_locale(db_locale_raw, default="") if db_locale_raw else ""
    locale = db_locale
    if not locale:
        locale = normalize_locale(getattr(update.effective_user, "language_code", None))
        await db_controller.set_user_language(user_id=user.id, language_code=locale, platform="tg")
    await _set_chat_commands(context, user.id, locale)

    logger.info(f"*** DB user: {db_user}")

    keyboard = [[KeyboardButton(tr("⏭ Пропустить", locale))]]

    if getattr(update.effective_chat, "type", "private") == "private":
        keyboard.insert(0, [KeyboardButton(tr("📍 Поделиться геолокацией", locale), request_location=True)])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        tr(
            "Привет, {name}!\nДля получения событий по твоему часовому поясу, тебе нужно поделиться геолокацией. Если ты живешь по Москоскому времени, то можешь нажать «Пропустить».",
            locale,
        ).format(name=user.first_name),
        reply_markup=reply_markup,
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")
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
    await update.message.reply_text(text=tr(text, locale))


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_location")

    location = update.message.location

    user = update.effective_chat
    tg_user = TgUser.model_validate(user)
    db_user = await db_controller.save_update_user(tg_user=tg_user)
    logger.info(f"*** DB user: {db_user}")

    logger.info(
        f"Пользователь {user.id} ({user.first_name}) поделился геолокацией: " f"широта={location.latitude}, долгота={location.longitude}"
    )
    tf = TimezoneFinder()

    tz_name = tf.timezone_at(lat=location.latitude, lng=location.longitude)
    logger.info(f"tz name; {tz_name}")
    locale_hint = normalize_locale(getattr(update.effective_user, "language_code", None), default="ru")
    city = await weather_service.resolve_city_from_coords(latitude=location.latitude, longitude=location.longitude, locale=locale_hint)
    if city:
        tg_user.city = city
        logger.info("Resolved weather city for user %s: %s", user.id, city)
    try:
        if not tz_name:
            raise ValueError("Timezone not detected from coordinates")
        now = datetime.now(ZoneInfo(tz_name))
        offset = now.utcoffset()

        tg_user.time_zone = tz_name
        await db_controller.save_update_user(tg_user=tg_user)
        logger.info(f"OFFSET: {offset}, {int(offset.total_seconds()/3600)}, {type(offset)}")
    except Exception:
        logger.exception("OFFSET ERR: ")
        await db_controller.save_update_user(tg_user=tg_user)

    await show_main_menu_keyboard(update.message)
    await show_calendar(update, context)


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_skip")

    user = update.effective_user
    logger.info(f"Пользователь {user.id} ({user.first_name}) пропустил геолокацию")

    await show_main_menu_keyboard(update.message)
    await show_calendar(update, context)


async def show_main_menu_keyboard(message: Message) -> None:
    locale = await resolve_user_locale(getattr(message, "chat_id", None), platform="tg")
    keyboard = [[tr("📅 Показать календарь", locale)], [tr("🗓 Ближайшие события", locale)], [tr("📝 Заметки", locale)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await message.reply_text(tr("Меню:", locale), reply_markup=reply_markup)


async def show_main_menu_keyboard_by_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    if not getattr(context, "bot", None):
        return
    locale = await resolve_user_locale(chat_id, platform="tg")
    keyboard = [[tr("📅 Показать календарь", locale)], [tr("🗓 Ближайшие события", locale)], [tr("📝 Заметки", locale)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await context.bot.send_message(chat_id=chat_id, text=tr("Меню:", locale), reply_markup=reply_markup)


async def show_main_menu(message: Message, add_text: str | None = None) -> None:
    logger.info("show_main_menu")

    locale = await resolve_user_locale(getattr(message, "chat_id", None), platform="tg")
    keyboard = [[tr("📅 Показать календарь", locale)], [tr("🗓 Ближайшие события", locale)], [tr("📝 Заметки", locale)]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    text = f"{add_text}\n\n{tr('Выберите действие:', locale)}" if add_text else tr("Выберите действие:", locale)

    await message.reply_text(text=text, reply_markup=reply_markup)


async def handle_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    args = getattr(context, "args", None) or []
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")
    if not args:
        await update.message.reply_text(tr("Use: /language ru|en", locale))
        return

    selected = normalize_locale(args[0], default="")
    if selected not in {"ru", "en"}:
        await update.message.reply_text(tr("Use: /language ru|en", locale))
        return

    await db_controller.set_user_language(user_id=update.effective_chat.id, language_code=selected, platform="tg")
    context.chat_data["locale"] = selected
    await _set_chat_commands(context, update.effective_chat.id, selected)
    if selected == "ru":
        await update.message.reply_text(tr("Язык переключен на русский.", selected))
    else:
        await update.message.reply_text(tr("Language switched to English.", selected))
    await show_main_menu_keyboard(update.message)
