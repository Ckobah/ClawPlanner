import datetime
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import fitz
from pypdf import PdfReader
from rapidocr_onnxruntime import RapidOCR
from telegram import Update
from telegram.ext import ContextTypes

from config import WHISPER_LANGUAGE, WHISPER_MODEL
from database.db_controller import db_controller
from entities import Event
from i18n import resolve_user_locale, tr

logger = logging.getLogger(__name__)

_whisper_model = None
_ocr_engine = None


@dataclass
class ParsedEvent:
    event_date: datetime.date
    start_time: datetime.time
    description: str


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(WHISPER_MODEL or "small", device="cpu", compute_type="int8")
    return _whisper_model


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = RapidOCR()
    return _ocr_engine


def _extract_date_from_segment(segment: str, base_date: datetime.date) -> datetime.date | None:
    low = segment.lower()
    if "послезавтра" in low:
        return base_date + datetime.timedelta(days=2)
    if "завтра" in low:
        return base_date + datetime.timedelta(days=1)
    if "сегодня" in low:
        return base_date

    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", segment)
    if not m:
        return None

    day = int(m.group(1))
    month = int(m.group(2))
    year_raw = m.group(3)
    if year_raw:
        year = int(year_raw)
        if year < 100:
            year += 2000
    else:
        year = base_date.year

    try:
        dt = datetime.date(year, month, day)
        if not year_raw and dt < base_date:
            dt = datetime.date(year + 1, month, day)
        return dt
    except ValueError:
        return None


def _extract_time_from_segment(segment: str) -> datetime.time | None:
    m = re.search(r"(?:\bв\s*)?([01]?\d|2[0-3])[:\.]([0-5]\d)\b", segment.lower())
    if not m:
        return None
    return datetime.time(int(m.group(1)), int(m.group(2)))


def _extract_description(segment: str) -> str:
    text = re.sub(r"\s+", " ", segment).strip()
    low = text.lower()

    for marker in ["по поводу", "насчет", "на тему", "о "]:
        pos = low.find(marker)
        if pos >= 0:
            value = text[pos + len(marker) :].strip(" .,!?:;-")
            if value:
                return value

    text = re.sub(r"\b(создай|создать|добавь|добавить|запланируй|поставь)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(сегодня|завтра|послезавтра)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:\bв\s*)?([01]?\d|2[0-3])[:\.]([0-5]\d)\b", "", text)
    text = re.sub(r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .,!?:;-")

    return text or "Событие"


async def parse_events_from_text(text: str, user_tz: str) -> list[ParsedEvent]:
    tz = ZoneInfo(user_tz)
    base_date = datetime.datetime.now(tz).date()

    chunks = [c.strip() for c in re.split(r"[\n;]+", text) if c.strip()]
    parsed: list[ParsedEvent] = []

    for chunk in chunks:
        event_date = _extract_date_from_segment(chunk, base_date)
        event_time = _extract_time_from_segment(chunk)
        if not event_time:
            continue
        if event_date is None:
            # для разговорной фразы с временем без даты считаем на завтра
            event_date = base_date + datetime.timedelta(days=1)

        description = _extract_description(chunk)
        parsed.append(ParsedEvent(event_date=event_date, start_time=event_time, description=description))

    return parsed


async def _save_parsed_events(parsed_events: list[ParsedEvent], user_id: int, tz_name: str) -> int:
    created = 0
    for item in parsed_events:
        event = Event(
            event_date=item.event_date,
            description=item.description,
            start_time=item.start_time,
            tg_id=user_id,
            creator_tg_id=user_id,
        )
        event_id = await db_controller.save_event(event=event, tz_name=tz_name)
        if event_id:
            created += 1
    return created


async def _process_extracted_text(update: Update, text: str) -> bool:
    if not update.message or not update.effective_chat:
        return False

    locale = await resolve_user_locale(update.effective_chat.id, platform="tg")
    user = await db_controller.get_user(update.effective_chat.id, platform="tg")
    tz_name = (getattr(user, "time_zone", None) or "Europe/Moscow") if user else "Europe/Moscow"

    parsed_events = await parse_events_from_text(text, user_tz=tz_name)
    if not parsed_events:
        await update.message.reply_text(tr("Не смог выделить события из файла/голоса. Пришли текстом в формате: 'завтра в 15:00 ...'", locale))
        return True

    created = await _save_parsed_events(parsed_events, user_id=update.effective_chat.id, tz_name=tz_name)
    if not created:
        await update.message.reply_text(tr("Не получилось записать события в календарь.", locale))
        return True

    lines = [tr("Добавил событий: {count}", locale).format(count=created)]
    for item in parsed_events[:10]:
        lines.append(f"• {item.event_date.strftime('%d.%m.%Y')} {item.start_time.strftime('%H:%M')} — {item.description}")
    await update.message.reply_text("\n".join(lines))
    return True


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat:
        return

    locale = await resolve_user_locale(update.effective_chat.id, platform="tg")
    voice = update.message.voice or update.message.audio
    if not voice:
        await update.message.reply_text(tr("Не вижу голосового сообщения.", locale))
        return

    with tempfile.TemporaryDirectory(prefix="tg_voice_") as tmp:
        ogg_path = Path(tmp) / "voice.ogg"
        file = await context.bot.get_file(voice.file_id)
        await file.download_to_drive(custom_path=str(ogg_path))

        model = _get_whisper_model()
        segments, _ = model.transcribe(str(ogg_path), language=(WHISPER_LANGUAGE or "ru"), vad_filter=True)
        text = " ".join(seg.text.strip() for seg in segments if seg.text).strip()

    if not text:
        await update.message.reply_text(tr("Не удалось распознать голосовое.", locale))
        return

    await _process_extracted_text(update, text)


async def handle_pdf_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.message.document:
        return

    locale = await resolve_user_locale(update.effective_chat.id, platform="tg")

    with tempfile.TemporaryDirectory(prefix="tg_pdf_") as tmp:
        pdf_path = Path(tmp) / (update.message.document.file_name or "input.pdf")
        file = await context.bot.get_file(update.message.document.file_id)
        await file.download_to_drive(custom_path=str(pdf_path))

        text_parts: list[str] = []

        try:
            reader = PdfReader(str(pdf_path))
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    text_parts.append(t)
        except Exception:
            logger.exception("pypdf extract failed")

        if not text_parts:
            try:
                doc = fitz.open(str(pdf_path))
                for page in doc:
                    t = page.get_text("text") or ""
                    if t.strip():
                        text_parts.append(t)
                doc.close()
            except Exception:
                logger.exception("fitz extract failed")

    text = "\n".join(text_parts).strip()
    if not text:
        await update.message.reply_text(tr("Не удалось извлечь текст из PDF.", locale))
        return

    await _process_extracted_text(update, text)


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.message.photo:
        return

    locale = await resolve_user_locale(update.effective_chat.id, platform="tg")

    with tempfile.TemporaryDirectory(prefix="tg_photo_") as tmp:
        image_path = Path(tmp) / "photo.jpg"
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        await file.download_to_drive(custom_path=str(image_path))

        ocr = _get_ocr_engine()
        result, _ = ocr(str(image_path))

    text_parts: list[str] = []
    if result:
        for item in result:
            if not item:
                continue
            try:
                text_parts.append(item[1])
            except Exception:
                continue

    text = "\n".join(text_parts).strip()
    if not text:
        await update.message.reply_text(tr("Не удалось распознать текст на фото.", locale))
        return

    await _process_extracted_text(update, text)
