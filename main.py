import asyncio
import datetime
import json
import logging
import os
import re
import shlex
import shutil
from typing import Any, Callable

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationBuilder,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

# ggg
from config import DEFAULT_TIMEZONE_NAME, SERVICE_ACCOUNTS, TOKEN, WEBHOOK_SECRET_TOKEN, WEBHOOK_URL
from database.db_controller import db_controller
from database.session import engine
from entities import Event
from handlers.cal import handle_calendar_callback, show_calendar
from handlers.contacts import handle_contact, handle_team_callback, handle_team_command
from handlers.events import (
    _get_back_button_state,
    generate_time_selector,
    get_event_constructor,
    handle_create_event_callback,
    handle_delete_event_callback,
    handle_edit_event_callback,
    handle_emoji_callback,
    handle_event_participants_callback,
    handle_participants_callback,
    handle_reschedule_event_callback,
    handle_time_callback,
    show_upcoming_events,
)
from handlers.link import handle_link_callback
from handlers.media import (
    handle_media_confirmation_callback,
    handle_pdf_message,
    handle_pending_event_clarification,
    handle_photo_message,
    handle_voice_message,
    parse_events_from_text,
)
from handlers.notes import handle_note_callback, handle_note_text_input, show_notes
from handlers.start import handle_help, handle_language, handle_location, handle_skip, show_main_menu_keyboard, start
from i18n import resolve_user_locale, tr, translate_markup

load_dotenv(".env")


logger = logging.getLogger(__name__)

AI_SESSION_PREFIX = os.getenv("AI_SESSION_PREFIX", "tg_planner_user")
AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "90"))
OPENCLAW_BIN = os.getenv("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/clawd/.npm-global/bin/openclaw"

RU_MONTHS_QUERY = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}


def _parse_allowed_ids(raw: str | None) -> set[int]:
    allowed: set[int] = set()
    for chunk in (raw or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            allowed.add(int(chunk))
        except ValueError:
            logger.warning("Skip invalid ALLOWED_TG_IDS value: %s", chunk)
    return allowed


ALLOWED_TG_IDS = _parse_allowed_ids(os.getenv("ALLOWED_TG_IDS"))


def _arg_get(args: tuple[Any, ...], kwargs: dict[str, Any], index: int, key: str) -> Any:
    if key in kwargs:
        return kwargs[key]
    if len(args) > index:
        return args[index]
    return None


def _arg_set(args: tuple[Any, ...], kwargs: dict[str, Any], index: int, key: str, value: Any) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if key in kwargs:
        kwargs[key] = value
        return args, kwargs
    mutable = list(args)
    while len(mutable) <= index:
        mutable.append(None)
    mutable[index] = value
    return tuple(mutable), kwargs


def patch_telegram_bot_i18n(bot: Any) -> None:
    if getattr(bot, "_i18n_patched", False):
        return

    original_send_message: Callable[..., Any] = bot.send_message
    original_edit_message_text: Callable[..., Any] = bot.edit_message_text
    original_edit_message_reply_markup: Callable[..., Any] = bot.edit_message_reply_markup

    async def send_message_i18n(*args: Any, **kwargs: Any) -> Any:
        chat_id = _arg_get(args, kwargs, 0, "chat_id")
        locale = await resolve_user_locale(chat_id, platform="tg")
        text = _arg_get(args, kwargs, 1, "text")
        if isinstance(text, str):
            args, kwargs = _arg_set(args, kwargs, 1, "text", tr(text, locale))
        reply_markup = _arg_get(args, kwargs, 2, "reply_markup")
        if reply_markup is not None:
            args, kwargs = _arg_set(args, kwargs, 2, "reply_markup", translate_markup(reply_markup, locale))
        return await original_send_message(*args, **kwargs)

    async def edit_message_text_i18n(*args: Any, **kwargs: Any) -> Any:
        text = _arg_get(args, kwargs, 0, "text")
        chat_id = _arg_get(args, kwargs, 1, "chat_id")
        locale = await resolve_user_locale(chat_id, platform="tg")
        if isinstance(text, str):
            args, kwargs = _arg_set(args, kwargs, 0, "text", tr(text, locale))
        reply_markup = _arg_get(args, kwargs, 7, "reply_markup")
        if reply_markup is not None:
            args, kwargs = _arg_set(args, kwargs, 7, "reply_markup", translate_markup(reply_markup, locale))
        return await original_edit_message_text(*args, **kwargs)

    async def edit_message_reply_markup_i18n(*args: Any, **kwargs: Any) -> Any:
        chat_id = _arg_get(args, kwargs, 0, "chat_id")
        locale = await resolve_user_locale(chat_id, platform="tg")
        reply_markup = _arg_get(args, kwargs, 3, "reply_markup")
        if reply_markup is not None:
            args, kwargs = _arg_set(args, kwargs, 3, "reply_markup", translate_markup(reply_markup, locale))
        return await original_edit_message_reply_markup(*args, **kwargs)

    try:
        bot.send_message = send_message_i18n  # type: ignore[method-assign]
        bot.edit_message_text = edit_message_text_i18n  # type: ignore[method-assign]
        bot.edit_message_reply_markup = edit_message_reply_markup_i18n  # type: ignore[method-assign]
        bot._i18n_patched = True
    except AttributeError:
        logger.warning("Telegram bot instance is immutable; runtime i18n patch is disabled for ExtBot.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, BadRequest):
        message = str(context.error)
        if "Message is not modified" in message:
            logger.info("Skip unchanged message update")
            return
        if "Query is too old" in message or "query id is invalid" in message:
            logger.info("Skip expired callback query")
            return
    logger.exception("Unhandled error", exc_info=context.error)


async def enforce_allowed_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ALLOWED_TG_IDS:
        return

    user_id = None
    if update.effective_user:
        user_id = update.effective_user.id
    elif update.effective_chat:
        user_id = update.effective_chat.id

    if user_id in ALLOWED_TG_IDS:
        return

    logger.warning("Access denied for tg_id=%s", user_id)

    try:
        if update.callback_query:
            await update.callback_query.answer("Доступ запрещен", show_alert=True)
        elif update.message:
            await update.message.reply_text("⛔ Доступ запрещен")
    except Exception:
        logger.exception("Failed to send access denied response")

    raise ApplicationHandlerStop


async def _build_user_context_block(user_id: int) -> str:
    user = await db_controller.get_user(user_id, platform="tg")
    if not user:
        return "Пользователь в БД не найден."

    user_name = user.first_name or user.username or "unknown"
    user_city = user.city or "unknown"
    user_tz = user.time_zone or DEFAULT_TIMEZONE_NAME

    # ближайшие события
    events_lines: list[str] = []
    try:
        nearest = await db_controller.get_nearest_events(user_id=user_id, tz_name=user_tz, platform="tg")
        for item in nearest[:8]:
            dt = list(item.keys())[0]
            desc, emoji = list(item.values())[0]
            events_lines.append(f"- {dt.strftime('%d.%m %H:%M')} {emoji or ''} {desc}".strip())
    except Exception:
        logger.exception("Failed to build nearest events context")

    # заметки
    notes_lines: list[str] = []
    try:
        row_id = await db_controller.get_user_row_id(external_id=user_id, platform="tg")
        if row_id is not None:
            notes = await db_controller.get_notes(user_id=row_id)
            for note in notes[:5]:
                txt = (note.note_text or "").strip().replace("\n", " ")
                notes_lines.append(f"- {txt[:120]}")
    except Exception:
        logger.exception("Failed to build notes context")

    return (
        f"Профиль пользователя:\n"
        f"- name: {user_name}\n"
        f"- city: {user_city}\n"
        f"- timezone: {user_tz}\n"
        f"Ближайшие события:\n{chr(10).join(events_lines) if events_lines else '- нет'}\n"
        f"Заметки:\n{chr(10).join(notes_lines) if notes_lines else '- нет'}"
    )


def _extract_date_from_query(text: str, user_tz: str) -> datetime.date | None:
    low = (text or "").lower()
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        now = now.astimezone(ZoneInfo(user_tz))
    except Exception:
        pass
    base_date = now.date()

    if "сегодня" in low:
        return base_date
    if "завтра" in low:
        return base_date + datetime.timedelta(days=1)
    if "послезавтра" in low:
        return base_date + datetime.timedelta(days=2)

    m_num = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", low)
    if m_num:
        day = int(m_num.group(1))
        month = int(m_num.group(2))
        y = m_num.group(3)
        year = int(y) + 2000 if y and len(y) == 2 else int(y) if y else base_date.year
        try:
            dt = datetime.date(year, month, day)
            if not y and dt < base_date:
                dt = datetime.date(year + 1, month, day)
            return dt
        except ValueError:
            return None

    m_ru = re.search(r"\b(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?\b", low)
    if m_ru:
        day = int(m_ru.group(1))
        mon_word = m_ru.group(2)
        year_raw = m_ru.group(3)
        month = next((v for k, v in RU_MONTHS_QUERY.items() if mon_word.startswith(k)), None)
        if month:
            year = int(year_raw) if year_raw else base_date.year
            try:
                dt = datetime.date(year, month, day)
                if not year_raw and dt < base_date:
                    dt = datetime.date(year + 1, month, day)
                return dt
            except ValueError:
                return None

    return None


async def _answer_profile_query(user_id: int, text: str) -> str | None:
    low = (text or "").lower().strip()
    if not low:
        return None

    user = await db_controller.get_user(user_id, platform="tg")
    if not user:
        return None

    if any(x in low for x in ["как меня зовут", "кто я", "моё имя", "мое имя", "my name", "who am i"]):
        name = user.first_name or user.username or "Не вижу имени в профиле"
        return f"Тебя зовут: {name}"

    if any(x in low for x in ["из какого я города", "мой город", "where am i from", "my city"]):
        city = user.city or "Город пока не указан"
        return f"Твой город: {city}"

    if any(x in low for x in ["что у меня запланировано", "какие у меня события", "что у меня на", "what do i have", "my events"]):
        user_tz = user.time_zone or DEFAULT_TIMEZONE_NAME
        target_date = _extract_date_from_query(low, user_tz)
        if not target_date:
            return "Уточни дату, пожалуйста: например, ‘на 8 марта’ или ‘на завтра’."

        events = await db_controller.get_current_day_events_by_user(
            user_id=user_id,
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
            tz_name=user_tz,
            platform="tg",
        )
        if not events:
            return f"На {target_date.strftime('%d.%m.%Y')} событий не нашёл."

        return f"На {target_date.strftime('%d.%m.%Y')} у тебя:\n{events}"

    if "когда у меня" in low or "when is my" in low:
        user_tz = user.time_zone or DEFAULT_TIMEZONE_NAME
        query_text = low
        for marker in ["когда у меня", "when is my"]:
            if marker in query_text:
                query_text = query_text.split(marker, 1)[1].strip(" ?!.,")
                break

        if len(query_text) < 2:
            return "Уточни, что именно ищем: например, ‘когда у меня стоматолог?’"

        found = await db_controller.find_events_by_description(
            user_id=user_id,
            query_text=query_text,
            tz_name=user_tz,
            platform="tg",
            limit=8,
        )
        if not found:
            return f"По запросу ‘{query_text}’ ничего не нашёл в описаниях событий."

        lines = [f"Нашёл по запросу ‘{query_text}’:"]
        for dt, desc in found[:8]:
            lines.append(f"- {dt.strftime('%d.%m.%Y %H:%M')} — {desc}")
        return "\n".join(lines)

    return None


async def ask_clawd(user_id: int, text: str) -> str:
    session_id = f"{AI_SESSION_PREFIX}_{user_id}"
    user = await db_controller.get_user(user_id, platform="tg")
    user_name = (user.first_name or user.username) if user else None
    user_tz = (user.time_zone or DEFAULT_TIMEZONE_NAME) if user else DEFAULT_TIMEZONE_NAME
    ctx_block = await _build_user_context_block(user_id)

    prompt = (
        "Ты помощник в Telegram. Отвечай кратко и по делу, предпочтительно на языке пользователя. "
        "У тебя есть актуальный контекст пользователя и его календаря/заметок ниже — используй его, не говори что у тебя нет доступа. "
        "Если для изменения календаря/заметок не хватает данных — задай 1-2 уточняющих вопроса. "
        "Если запрос общий — просто помоги.\n\n"
        f"Контекст: name={user_name or 'unknown'}, timezone={user_tz}.\n"
        f"{ctx_block}\n\n"
        f"Сообщение пользователя: {text}"
    )

    cmd = (
        f"export PATH=/home/clawd/.npm-global/bin:$PATH; "
        f"{shlex.quote(OPENCLAW_BIN)} agent "
        f"--session-id {shlex.quote(session_id)} "
        f"--message {shlex.quote(prompt)} "
        f"--json --timeout {AI_TIMEOUT_SECONDS}"
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            f"/bin/bash -lc {shlex.quote(cmd)}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except Exception:
        logger.exception("Failed to run openclaw agent via %s", OPENCLAW_BIN)
        return "Сейчас не могу обратиться к OpenClaw. Попробуй ещё раз чуть позже."

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="ignore").strip()
        logger.error("openclaw agent failed: %s", err)
        return "Не получилось обработать запрос прямо сейчас."

    try:
        payload = json.loads(stdout.decode("utf-8", errors="ignore"))
        result = (payload.get("result") or {}) if isinstance(payload, dict) else {}
        parts = result.get("payloads") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
        answer = "\n\n".join(texts).strip()
        return answer or "Нужен чуть более конкретный запрос 🙂"
    except Exception:
        logger.exception("Failed to parse openclaw agent response")
        return "Не смог разобрать ответ OpenClaw. Попробуй ещё раз."


async def _try_create_note_from_free_text(update: Update, locale: str | None = None) -> bool:
    if not update.message or not update.effective_chat:
        return False

    text = (update.message.text or "").strip()
    if not text:
        return False

    low = text.lower()

    # Явные маркеры заметки (ru/en)
    note_markers = [
        "заметк", "note", "notes", "memo",
        "запиши", "запомни", "remember",
    ]
    if not any(m in low for m in note_markers):
        return False

    # Извлекаем текст заметки
    note_text = text

    m = re.search(
        r"^(?:добавь|создай|сделай|запиши|запомни|add|create|make|remember)\s+(?:мне\s+)?(?:новую\s+)?(?:заметку|note|memo)[:\-\s]*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if m:
        note_text = m.group(1).strip()
    else:
        m2 = re.search(r"^(?:заметка|note|memo)[:\-\s]+(.+)$", text, flags=re.IGNORECASE)
        if m2:
            note_text = m2.group(1).strip()

    if not note_text:
        return False

    note_user_id = await db_controller.get_user_row_id(external_id=update.effective_chat.id, platform="tg")
    if note_user_id is None:
        return False

    await db_controller.create_note(user_id=note_user_id, note_text=note_text)
    await update.message.reply_text(tr("📝 Заметка сохранена", locale))
    return True


async def _try_create_events_from_free_text(update: Update, locale: str | None = None) -> bool:
    if not update.message or not update.effective_chat:
        return False

    text = (update.message.text or "").strip()
    if not text:
        return False

    # не срабатываем на короткий бытовой чат без временных/событийных маркеров
    low = text.lower()
    intent_markers = [
        "завтра", "сегодня", "послезавтра", "в ", "создай", "добавь", "встреч", "ежегод", "каждый",
        "tomorrow", "today", "day after tomorrow", "create", "add", "schedule", "meeting", "event", "every", "at ",
        ":", ".",
    ]
    if not any(x in low for x in intent_markers):
        return False

    user_id = update.effective_chat.id
    user = await db_controller.get_user(user_id, platform="tg")
    tz_name = (getattr(user, "time_zone", None) or "Europe/Moscow") if user else "Europe/Moscow"

    parsed = await parse_events_from_text(text, user_tz=tz_name)
    if not parsed:
        return False

    created = 0
    for item in parsed:
        event = Event(
            event_date=item.event_date,
            description=item.description,
            start_time=item.start_time,
            stop_time=item.stop_time,
            recurrent=item.recurrent,
            tg_id=user_id,
            creator_tg_id=user_id,
        )
        event_id = await db_controller.save_event(event=event, tz_name=tz_name)
        if event_id:
            created += 1

    if created:
        await update.message.reply_text(tr("Готово ✅ Добавил событий: {count}", locale).format(count=created))
        return True

    return False


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_text")
    logger.info(update)
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")

    if update.message and update.effective_chat:
        quick_answer = await _answer_profile_query(update.effective_chat.id, update.message.text or "")
        if quick_answer:
            await update.message.reply_text(quick_answer)
            return

    if await handle_pending_event_clarification(update, context):
        return

    if await handle_note_text_input(update, context, locale):
        return

    await_time_input = context.chat_data.get("await_time_input")
    if await_time_input:
        event = context.chat_data.get("event")
        if not event:
            context.chat_data.pop("await_time_input", None)
            await update.message.reply_text(tr("Событие не найдено. Откройте создание события заново.", locale))
            return

        raw_value = (update.message.text or "").strip()
        if not raw_value.isdigit():
            await update.message.reply_text(tr("Введите число.", locale))
            return

        value = int(raw_value)
        field = await_time_input.get("field")
        time_type = await_time_input.get("time_type")

        if field == "hour" and not (0 <= value <= 23):
            await update.message.reply_text(tr("Часы должны быть от 0 до 23.", locale))
            return

        if field == "minute" and not (0 <= value <= 59):
            await update.message.reply_text(tr("Минуты должны быть от 0 до 59.", locale))
            return

        base_time = event.start_time if time_type == "start" else event.stop_time
        if base_time is None:
            if time_type == "stop" and event.start_time:
                base_time = event.start_time
            else:
                base_time = datetime.time(12, 0)

        hours = base_time.hour
        minutes = base_time.minute
        if field == "hour":
            hours = value
        elif field == "minute":
            minutes = value

        selected_time = datetime.time(hours, minutes)
        if time_type == "start":
            event.start_time = selected_time
        else:
            event.stop_time = selected_time

        context.chat_data["event"] = event
        prompt_message_id = await_time_input.get("prompt_message_id")
        prompt_chat_id = await_time_input.get("prompt_chat_id")
        if not prompt_message_id or not prompt_chat_id:
            prompt_message_id = context.chat_data.get("time_input_prompt_message_id")
            prompt_chat_id = context.chat_data.get("time_input_prompt_chat_id")
        context.chat_data.pop("await_time_input", None)
        context.chat_data.pop("time_input_prompt_message_id", None)
        context.chat_data.pop("time_input_prompt_chat_id", None)

        reply_markup = generate_time_selector(hours=hours, minutes=minutes, time_type=time_type)
        chat_id = context.chat_data.get("time_picker_chat_id")
        message_id = context.chat_data.get("time_picker_message_id")
        if chat_id and message_id:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
        else:
            await update.message.reply_text(tr("Готово.", locale), reply_markup=reply_markup)

        if update.message:
            try:
                await context.bot.delete_message(
                    chat_id=update.message.chat_id,
                    message_id=update.message.message_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to delete user time input message")

        if prompt_message_id and prompt_chat_id:
            try:
                await context.bot.delete_message(
                    chat_id=prompt_chat_id,
                    message_id=prompt_message_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to delete time input prompt message")

        return

    await_event_description = context.chat_data.get("await_event_description")
    if await_event_description:
        event = context.chat_data.get("event")
        event.description = update.message.text
        context.chat_data["event"] = event
        has_participants = bool(event.all_user_participants)

        year, month, day = event.get_date()
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
        target_message_id = None
        target_chat_id = None
        prompt_message_id = None
        prompt_chat_id = None
        if isinstance(await_event_description, dict):
            target_message_id = await_event_description.get("message_id")
            target_chat_id = await_event_description.get("chat_id")
            prompt_message_id = await_event_description.get("prompt_message_id")
            prompt_chat_id = await_event_description.get("prompt_chat_id")
        if target_message_id and target_chat_id:
            await context.bot.edit_message_text(
                chat_id=target_chat_id,
                message_id=target_message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="HTML")

        # получаем кнопки
        context.chat_data.pop("await_event_description", None)

        if update.message:
            try:
                await context.bot.delete_message(
                    chat_id=update.message.chat_id,
                    message_id=update.message.message_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to delete user description message")

        if prompt_message_id and prompt_chat_id:
            try:
                await context.bot.delete_message(
                    chat_id=prompt_chat_id,
                    message_id=prompt_message_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to delete description prompt message")

        return

    if await _try_create_note_from_free_text(update, locale):
        return

    if await _try_create_events_from_free_text(update, locale):
        return

    if update.message and update.effective_chat:
        answer = await ask_clawd(update.effective_chat.id, update.message.text or "")
        await update.message.reply_text(answer)
        return

    await update.message.reply_text(tr("Используйте кнопки для навигации.", locale))


async def handle_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None and update.message:
        user_id = update.message.chat_id
    if user_id is None:
        await update.message.reply_text(tr("Не удалось определить ваш ID.", locale))
        return
    await update.message.reply_text(tr("Ваш ID: {user_id}", locale).format(user_id=user_id))


async def all_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("ALL callbacks")
    logger.info(f"*** {update}")
    query = update.callback_query
    await query.answer()


async def set_commands(app):
    commands_ru = [
        BotCommand("start", "Запустить бота"),
        BotCommand("my_id", "Показать мой Telegram ID"),
        BotCommand("team", "Управление участниками"),
        BotCommand("help", "Помощь"),
        BotCommand("language", "Сменить язык"),
    ]
    commands_en = [
        BotCommand("start", "Start bot"),
        BotCommand("my_id", "Show my Telegram ID"),
        BotCommand("team", "Manage participants"),
        BotCommand("help", "Help"),
        BotCommand("language", "Change language"),
    ]
    await app.bot.set_my_commands(commands_ru, language_code="ru")
    await app.bot.set_my_commands(commands_en, language_code="en")
    await app.bot.set_my_commands(commands_en)
    if SERVICE_ACCOUNTS:
        try:
            for service_account in SERVICE_ACCOUNTS.split(";"):
                await app.bot.send_message(chat_id=service_account, text="App started")
        except:  # noqa
            logger.exception("err ")


async def shutdown(app):
    await engine.dispose()


def main() -> None:
    application = ApplicationBuilder().token(TOKEN).post_shutdown(shutdown).build()
    patch_telegram_bot_i18n(application.bot)

    # Access guard for private bot usage
    application.add_handler(TypeHandler(Update, enforce_allowed_users), group=-1)

    # start, Получение геолокации и Пропуск геолокации
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("language", handle_language))
    application.add_handler(CommandHandler("team", handle_team_command))
    application.add_handler(CommandHandler("my_id", handle_my_id))
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    application.add_handler(MessageHandler(filters.Regex(r"^⏭ (Пропустить|Skip)$"), handle_skip))

    # Календарь
    application.add_handler(MessageHandler(filters.Regex(r"^📅 (Показать календарь|Show calendar)$"), show_calendar))
    application.add_handler(CallbackQueryHandler(handle_calendar_callback, pattern="^cal_"))

    # Создание\удаление события
    application.add_handler(CallbackQueryHandler(handle_time_callback, pattern="^time_"))
    application.add_handler(CallbackQueryHandler(handle_create_event_callback, pattern="^create_event_"))
    application.add_handler(CallbackQueryHandler(handle_edit_event_callback, pattern="^edit_event_"))
    application.add_handler(CallbackQueryHandler(handle_delete_event_callback, pattern="^delete_event_"))
    application.add_handler(CallbackQueryHandler(handle_participants_callback, pattern="^participants_"))
    application.add_handler(CallbackQueryHandler(handle_team_callback, pattern="^team_"))
    application.add_handler(CallbackQueryHandler(handle_event_participants_callback, pattern="^create_participant_event_"))
    application.add_handler(CallbackQueryHandler(handle_reschedule_event_callback, pattern="^reschedule_event_"))
    application.add_handler(CallbackQueryHandler(handle_emoji_callback, pattern="^emoji_"))
    application.add_handler(CallbackQueryHandler(handle_link_callback, pattern="^link_tg_"))
    application.add_handler(CallbackQueryHandler(handle_media_confirmation_callback, pattern="^media_confirm_"))
    application.add_handler(CallbackQueryHandler(handle_note_callback, pattern="^note_"))
    application.add_handler(MessageHandler(filters.Regex(r"^🗓 (Ближайшие события|Upcoming events)$"), show_upcoming_events))
    application.add_handler(MessageHandler(filters.Regex(r"^(📝 )?(Заметки|Notes)$"), show_notes))

    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf_message))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.add_handler(CallbackQueryHandler(all_callbacks))
    application.add_error_handler(error_handler)

    application.post_init = set_commands

    logger.info("Бот запущен...")

    if WEBHOOK_URL:
        logger.info(f"Через webhook {WEBHOOK_URL}")
        application.run_webhook(
            listen="0.0.0.0",  # noqa
            port=8001,
            secret_token=WEBHOOK_SECRET_TOKEN,
            webhook_url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("Через Long polling")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
