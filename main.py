import asyncio
import datetime
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader
from faster_whisper import WhisperModel
from rapidocr_onnxruntime import RapidOCR
import fitz

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
    filters,
)

# ggg
from config import DEFAULT_TIMEZONE_NAME, SERVICE_ACCOUNTS, TOKEN, WEBHOOK_SECRET_TOKEN, WEBHOOK_URL
from database.db_controller import db_controller
from database.session import engine
from entities import Event
from handlers.cal import handle_calendar_callback, show_calendar
from handlers.contacts import handle_contact
from handlers.events import (
    generate_time_selector,
    get_event_constructor,
    _get_back_button_state,
    handle_create_event_callback,
    handle_delete_event_callback,
    handle_edit_event_callback,
    handle_emoji_callback,
    # participants handlers disabled for single-user calendar mode,
    handle_reschedule_event_callback,
    handle_time_callback,
    show_upcoming_events,
)
from handlers.link import handle_link_callback
from handlers.start import handle_help, handle_language, handle_location, handle_skip, start
from i18n import resolve_user_locale, tr, translate_markup

load_dotenv(".env")


logger = logging.getLogger(__name__)


def _parse_ids_csv(value: str | None) -> set[int]:
    if not value:
        return set()
    out: set[int] = set()
    for x in value.split(","):
        x = x.strip()
        if not x:
            continue
        out.add(int(x))
    return out


ALLOWED_TG_IDS: set[int] = _parse_ids_csv(os.getenv("ALLOWED_TG_IDS", "123456789"))
AI_SESSION_PREFIX = os.getenv("AI_SESSION_PREFIX", "tg_planner_user")
AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "90"))
OPENCLAW_BIN = os.getenv("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/clawd/.npm-global/bin/openclaw"
WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "small")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "ru")
_whisper_model: WhisperModel | None = None
_ocr_engine: RapidOCR | None = None


def _is_calendar_text(text: str) -> bool:
    text_l = (text or "").lower().strip()
    if not text_l:
        return False
    keywords = (
        "календар", "событ", "встреч", "напомин", "дата", "время", "перенес", "перенос", "удалить событие", "создать событие", "создай", "добавь", "напомни",
        "tg_users", "часовой пояс", "таймзона", "timezone", "язык", "language",
        "calendar", "event", "remind", "meeting", "schedule",
    )
    return any(k in text_l for k in keywords)


def _has_datetime_cues(text: str) -> bool:
    text_l = (text or "").lower().strip()
    if not text_l:
        return False

    # Explicit date/time markers
    if re.search(r"\b\d{1,2}:\d{2}\b", text_l):
        return True
    if re.search(r"\b\d{1,2}[./-]\d{1,2}([./-]\d{2,4})?\b", text_l):
        return True

    weekday_markers = (
        "понедель", "вторник", "сред", "четвер", "пятниц", "суббот", "воскрес",
        "завтра", "послезавтра", "сегодня",
    )
    if any(w in text_l for w in weekday_markers):
        return True

    return False


def _has_event_action_cues(text: str) -> bool:
    text_l = (text or "").lower().strip()
    if not text_l:
        return False
    markers = (
        "создай", "добавь", "заплан", "напомни", "встреч", "поездк", "еду", "иду", "буду",
        "create", "add", "schedule", "plan", "remind",
    )
    return any(m in text_l for m in markers)


def _is_non_event_query(text: str) -> bool:
    text_l = (text or "").lower().strip()
    if not text_l:
        return False
    markers = (
        "погод", "weather", "температур", "дожд", "снег", "ветер",
        "новост", "news", "курс", "доллар", "евро",
    )
    return any(m in text_l for m in markers)


def _is_name_query(text: str) -> bool:
    text_l = (text or "").lower().strip()
    if not text_l:
        return False
    markers = (
        "как меня зовут", "моё имя", "мое имя", "как зовут", "кто я",
        "my name", "what is my name", "who am i",
    )
    return any(m in text_l for m in markers)


def _is_profile_query(text: str) -> bool:
    text_l = (text or "").lower().strip()
    if not text_l:
        return False
    markers = (
        "tg_users", "часовой пояс", "таймзона", "timezone", "язык", "language", "профиль",
    )
    return any(m in text_l for m in markers)


async def ask_clawd(user_id: int, text: str) -> str:
    session_id = f"{AI_SESSION_PREFIX}_{user_id}"
    user = await db_controller.get_user(user_id, platform="tg")
    user_name = (user.first_name or user.username) if user else None
    user_tz = (user.time_zone or DEFAULT_TIMEZONE_NAME) if user else DEFAULT_TIMEZONE_NAME

    prompt = (
        "Ты помогаешь пользователю в Telegram. "
        "Отвечай кратко и по делу, на русском языке.\n"
        "Если у тебя уже есть timezone пользователя, никогда не проси его повторно.\n"
        "Если пользователь просит создать событие и есть дата/время/описание — сразу создавай, без вопросов про TZ.\n\n"
        f"Контекст профиля: name={user_name or 'unknown'}, timezone={user_tz}.\n"
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
        return "AI-модуль сейчас недоступен. Попробуй ещё раз чуть позже."

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="ignore").strip()
        logger.error("openclaw agent failed: %s", err)
        return "Не смог обработать запрос прямо сейчас. Попробуй ещё раз через минуту."

    try:
        payload = json.loads(stdout.decode("utf-8", errors="ignore"))
        result = (payload.get("result") or {}) if isinstance(payload, dict) else {}
        stop_reason = (result.get("stopReason") or result.get("stop_reason") or "").lower()

        if stop_reason == "error":
            logger.error("openclaw agent stop_reason=error: %s", payload)
            return "Сейчас не получилось обработать запрос. Попробуй ещё раз через минуту."

        parts = result.get("payloads") or []
        texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")]
        answer = "\n\n".join(texts).strip()

        if "Unhandled stop reason: error" in answer:
            logger.error("openclaw returned unhandled stop reason in text: %s", answer)
            return "Сейчас не получилось обработать запрос. Попробуй ещё раз через минуту."

        return answer or "Пустой ответ от AI. Попробуй переформулировать запрос."
    except Exception:
        logger.exception("Failed to parse openclaw agent response")
        return "Не смог обработать ответ. Попробуй ещё раз."


def _get_whisper_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type="int8")
    return _whisper_model


def _transcribe_audio_sync(path: str) -> str:
    model = _get_whisper_model()
    segments, _info = model.transcribe(path, language=WHISPER_LANGUAGE, vad_filter=True)
    text_parts = [seg.text.strip() for seg in segments if seg.text and seg.text.strip()]
    return " ".join(text_parts).strip()


def _get_ocr_engine() -> RapidOCR:
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _ocr_image_sync(path: str) -> str:
    ocr = _get_ocr_engine()
    result, _ = ocr(path)
    if not result:
        return ""
    lines: list[str] = []
    for item in result:
        try:
            txt = (item[1] or "").strip()
            if txt:
                lines.append(txt)
        except Exception:
            continue
    return "\n".join(lines).strip()


def _ocr_pdf_sync(path: str, max_pages: int = 8) -> str:
    doc = fitz.open(path)
    chunks: list[str] = []
    try:
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            tmp_img = Path(tempfile.gettempdir()) / "tg_bot_clawd" / f"ocr_{os.getpid()}_{i}.png"
            tmp_img.parent.mkdir(parents=True, exist_ok=True)
            pix.save(str(tmp_img))
            txt = _ocr_image_sync(str(tmp_img))
            if txt:
                chunks.append(txt)
    finally:
        doc.close()
    return "\n\n".join(chunks).strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # Remove fenced blocks if present.
    if "```" in raw:
        raw = raw.replace("```json", "```").replace("```", "")
    # Best-effort: parse full text first, then first {...} fragment.
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


async def parse_event_from_image(user_id: int, image_path: str) -> dict[str, Any] | None:
    source_text = await asyncio.to_thread(_ocr_image_sync, image_path)
    if not source_text:
        return None
    return await parse_event_from_text(user_id=user_id, source_text=source_text, source_label="image")


async def parse_event_from_text(user_id: int, source_text: str, source_label: str = "pdf") -> dict[str, Any] | None:
    session_id = f"{AI_SESSION_PREFIX}_text_{user_id}"
    today = datetime.date.today().isoformat()
    prompt = (
        f"Ниже текст из {source_label}. Извлеки данные события. "
        "Верни только JSON без пояснений в формате:\n"
        "{\n"
        "  \"title\": \"...\",\n"
        "  \"description\": \"...\",\n"
        "  \"event_date\": \"YYYY-MM-DD\",\n"
        "  \"start_time\": \"HH:MM\",\n"
        "  \"end_time\": \"HH:MM|null\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"source_text\": \"краткий фрагмент\"\n"
        "}\n"
        f"Сегодня: {today}. Часовой пояс Europe/Moscow.\n\n"
        f"Текст:\n{source_text[:12000]}"
    )

    cmd = (
        f"export PATH=/home/clawd/.npm-global/bin:$PATH; "
        f"{shlex.quote(OPENCLAW_BIN)} agent "
        f"--session-id {shlex.quote(session_id)} "
        f"--message {shlex.quote(prompt)} "
        f"--json --timeout {AI_TIMEOUT_SECONDS}"
    )

    proc = await asyncio.create_subprocess_shell(
        f"/bin/bash -lc {shlex.quote(cmd)}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.error("text parse agent failed: %s", stderr.decode("utf-8", errors="ignore"))
        return None

    payload = json.loads(stdout.decode("utf-8", errors="ignore"))
    parts = (payload.get("result") or {}).get("payloads") or []
    text = "\n\n".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    return _extract_json_object(text)


async def _save_parsed_event(update: Update, wait_msg, parsed: dict[str, Any], locale: str) -> None:
    date_s = (parsed.get("event_date") or "").strip()
    start_s = (parsed.get("start_time") or "").strip() or "12:00"
    end_s = (parsed.get("end_time") or "").strip()

    try:
        event_date = datetime.date.fromisoformat(date_s)
    except Exception:
        event_date = datetime.date.today()

    try:
        start_time = datetime.time.fromisoformat(start_s)
    except Exception:
        start_time = datetime.time(12, 0)

    stop_time = None
    if end_s and end_s.lower() != "null":
        try:
            stop_time = datetime.time.fromisoformat(end_s)
        except Exception:
            stop_time = None

    title = (parsed.get("title") or "").strip()
    desc = (parsed.get("description") or "").strip()
    description = (title + (" — " + desc if desc else "")).strip() or "Событие"

    event = Event(
        event_date=event_date,
        description=description,
        start_time=start_time,
        stop_time=stop_time,
        tg_id=update.effective_user.id,
        creator_tg_id=update.effective_user.id,
        participants=[update.effective_user.id],
    )

    event_id = await db_controller.save_event(event=event, tz_name=DEFAULT_TIMEZONE_NAME)
    if event_id:
        await db_controller.set_event_participants(event_id=event_id, participant_ids=event.participants)

    await wait_msg.edit_text(
        tr("Готово. Добавил событие: {description}\nДата: {date}\nВремя: {time}", locale).format(
            description=description,
            date=event_date.isoformat(),
            time=start_time.strftime("%H:%M"),
        )
    )


async def handle_photo_or_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")
    wait_msg = await update.message.reply_text(tr("Распознаю афишу/билет и добавляю событие…", locale))

    try:
        photo = update.message.photo[-1] if update.message.photo else None
        doc = update.message.document if update.message.document else None
        if not photo and not doc:
            await wait_msg.edit_text(tr("Не нашёл изображение в сообщении.", locale))
            return

        telegram_file = await (photo.get_file() if photo else doc.get_file())
        suffix = ".jpg"
        if doc and doc.file_name and "." in doc.file_name:
            suffix = Path(doc.file_name).suffix or suffix

        tmp_dir = Path(tempfile.gettempdir()) / "tg_bot_clawd"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        local_path = tmp_dir / f"event_{update.effective_user.id}_{int(datetime.datetime.utcnow().timestamp())}{suffix}"
        await telegram_file.download_to_drive(custom_path=str(local_path))

        parsed = await parse_event_from_image(update.effective_user.id, str(local_path))
        if not parsed:
            await wait_msg.edit_text(tr("Не смог распознать событие на изображении. Попробуй более чёткое фото.", locale))
            return

        await _save_parsed_event(update, wait_msg, parsed, locale)
    except Exception:
        logger.exception("Failed to process image event")
        await wait_msg.edit_text(tr("Не удалось обработать изображение. Попробуй ещё раз.", locale))


async def handle_pdf_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document:
        return

    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")
    wait_msg = await update.message.reply_text(tr("Читаю PDF, извлекаю событие и добавляю в календарь…", locale))

    try:
        doc = update.message.document
        telegram_file = await doc.get_file()

        tmp_dir = Path(tempfile.gettempdir()) / "tg_bot_clawd"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(doc.file_name).suffix if doc.file_name and "." in doc.file_name else ".pdf"
        local_path = tmp_dir / f"event_pdf_{update.effective_user.id}_{int(datetime.datetime.utcnow().timestamp())}{suffix}"
        await telegram_file.download_to_drive(custom_path=str(local_path))

        reader = PdfReader(str(local_path))
        chunks: list[str] = []
        for page in reader.pages[:15]:
            txt = page.extract_text() or ""
            if txt.strip():
                chunks.append(txt)
        source_text = "\n\n".join(chunks).strip()

        if not source_text:
            source_text = await asyncio.to_thread(_ocr_pdf_sync, str(local_path))

        if not source_text:
            await wait_msg.edit_text(tr("Не смог извлечь текст из PDF даже через OCR. Попробуй более чёткий файл.", locale))
            return

        parsed = await parse_event_from_text(update.effective_user.id, source_text, source_label="pdf")
        if not parsed:
            await wait_msg.edit_text(tr("Не смог извлечь событие из PDF. Попробуй другой файл или фото.", locale))
            return

        await _save_parsed_event(update, wait_msg, parsed, locale)
    except Exception:
        logger.exception("Failed to process PDF event")
        await wait_msg.edit_text(tr("Не удалось обработать PDF. Попробуй ещё раз.", locale))


async def handle_voice_or_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")
    wait_msg = await update.message.reply_text(tr("Слушаю голосовое…", locale))

    try:
        voice = update.message.voice
        audio = update.message.audio
        media = voice or audio
        if not media:
            await wait_msg.edit_text(tr("Не нашёл аудио в сообщении.", locale))
            return

        telegram_file = await media.get_file()
        tmp_dir = Path(tempfile.gettempdir()) / "tg_bot_clawd"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        local_path = tmp_dir / f"voice_{update.effective_user.id}_{int(datetime.datetime.utcnow().timestamp())}.ogg"
        await telegram_file.download_to_drive(custom_path=str(local_path))

        text = await asyncio.to_thread(_transcribe_audio_sync, str(local_path))
        if not text:
            await wait_msg.edit_text(tr("Не смог распознать речь. Попробуй запись погромче/чётче.", locale))
            return

        # Календарный intent -> извлекаем структуру события и сохраняем.
        if _is_calendar_text(text):
            parsed = await parse_event_from_text(update.effective_user.id, text, source_label="voice")
            if parsed:
                await _save_parsed_event(update, wait_msg, parsed, locale)
                return

        # Иначе обычный AI-ответ.
        answer = await ask_clawd(update.effective_user.id, text)
        await wait_msg.edit_text(f"📝 Распознал: {text}\n\n🤖 {answer}"[:3900])
    except Exception:
        logger.exception("Failed to process voice/audio")
        await wait_msg.edit_text(tr("Не удалось обработать голосовое. Попробуй ещё раз.", locale))


async def access_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    if ALLOWED_TG_IDS and user.id not in ALLOWED_TG_IDS:
        logger.info("Ignoring update from unauthorized tg_id=%s", user.id)
        raise ApplicationHandlerStop


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


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("handle_text")
    logger.info(update)
    locale = await resolve_user_locale(getattr(update.effective_chat, "id", None), platform="tg")

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

    text = (update.message.text or "").strip()
    user_id = update.effective_user.id if update.effective_user else update.effective_chat.id

    if _is_name_query(text):
        user = await db_controller.get_user(user_id, platform="tg")
        if user:
            display_name = user.first_name or user.username
            if display_name:
                await update.message.reply_text(tr("Вас зовут: {name}", locale).format(name=display_name))
                return
        await update.message.reply_text(tr("Пока не вижу имени в базе. Напишите, как к вам обращаться.", locale))
        return

    if _is_profile_query(text):
        user = await db_controller.get_user(user_id, platform="tg")
        if user:
            display_name = user.first_name or user.username or str(user_id)
            tz = user.time_zone or DEFAULT_TIMEZONE_NAME
            lang = user.language_code or "ru"
            await update.message.reply_text(
                tr("Профиль из tg_users:\nИмя: {name}\nЧасовой пояс: {tz}\nЯзык: {lang}", locale).format(
                    name=display_name,
                    tz=tz,
                    lang=lang,
                )
            )
            return

    should_try_event_parse = (
        _is_calendar_text(text)
        or (_has_datetime_cues(text) and _has_event_action_cues(text) and not _is_non_event_query(text))
    )

    if should_try_event_parse:
        parsed = await parse_event_from_text(user_id=user_id, source_text=text, source_label="text")
        if parsed and (parsed.get("event_date") or parsed.get("start_time") or parsed.get("title") or parsed.get("description")):
            status_msg = await update.message.reply_text(tr("Понял запрос по событию, добавляю в календарь…", locale))
            await _save_parsed_event(update, status_msg, parsed, locale)
            return

        # If it sounds calendar-related but we could not parse explicit event fields,
        # fall through to AI dialogue instead of dead-end button hint.

    answer = await ask_clawd(user_id=user_id, text=text)
    await update.message.reply_text(answer[:3900])


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
        # BotCommand("team", "Управление участниками"),
        BotCommand("help", "Помощь"),
        BotCommand("language", "Сменить язык"),
    ]
    commands_en = [
        BotCommand("start", "Start bot"),
        BotCommand("my_id", "Show my Telegram ID"),
        # BotCommand("team", "Manage participants"),
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

    # Access guard first (separate group). Do not block authorized updates.
    application.add_handler(MessageHandler(filters.ALL, access_guard), group=-1)
    application.add_handler(CallbackQueryHandler(access_guard, pattern=".*"), group=-1)

    # start, Получение геолокации и Пропуск геолокации
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", handle_help))
    application.add_handler(CommandHandler("language", handle_language))
    # application.add_handler(CommandHandler("team", handle_team_command))
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
    # participants/team callbacks disabled in single-user calendar mode
    application.add_handler(CallbackQueryHandler(handle_reschedule_event_callback, pattern="^reschedule_event_"))
    application.add_handler(CallbackQueryHandler(handle_emoji_callback, pattern="^emoji_"))
    application.add_handler(CallbackQueryHandler(handle_link_callback, pattern="^link_tg_"))
    application.add_handler(MessageHandler(filters.Regex(r"^🗓 (Ближайшие события|Upcoming events)$"), show_upcoming_events))

    application.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf_document))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo_or_image))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_or_audio))
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
