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
from entities import Event, Recurrent
from i18n import resolve_user_locale, tr

logger = logging.getLogger(__name__)

_whisper_model = None
_ocr_engine = None


@dataclass
class ParsedEvent:
    event_date: datetime.date
    start_time: datetime.time
    description: str
    recurrent: Recurrent = Recurrent.never


RU_MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}

EN_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

WEEKDAYS_RU = {
    "понедельник": 0,
    "вторник": 1,
    "сред": 2,
    "четверг": 3,
    "пятниц": 4,
    "суббот": 5,
    "воскрес": 6,
}

WEEKDAYS_EN = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


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

    # relative days ru/en
    if "послезавтра" in low or "day after tomorrow" in low:
        return base_date + datetime.timedelta(days=2)
    if "завтра" in low or "tomorrow" in low:
        return base_date + datetime.timedelta(days=1)
    if "сегодня" in low or "today" in low:
        return base_date

    # weekdays ru/en: "в понедельник", "on monday", "next monday"
    for word, idx in {**WEEKDAYS_RU, **WEEKDAYS_EN}.items():
        if word in low:
            delta = (idx - base_date.weekday()) % 7
            if delta == 0 or "next" in low or "следующ" in low:
                delta = 7 if delta == 0 else delta
            return base_date + datetime.timedelta(days=delta)

    # ru month words: 23 февраля [2026]
    m_ru = re.search(r"\b(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?\b", low)
    if m_ru:
        day = int(m_ru.group(1))
        mon_word = m_ru.group(2)
        year_raw = m_ru.group(3)
        month = next((v for k, v in RU_MONTHS.items() if mon_word.startswith(k)), None)
        if month:
            year = int(year_raw) if year_raw else base_date.year
            try:
                dt = datetime.date(year, month, day)
                if not year_raw and dt < base_date:
                    dt = datetime.date(year + 1, month, day)
                return dt
            except ValueError:
                pass

    # en month words: Feb 23 [2026] / 23 Feb [2026]
    m_en1 = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})(?:,?\s*(\d{4}))?\b", low)
    m_en2 = re.search(r"\b(\d{1,2})\s+([a-z]{3,9})(?:,?\s*(\d{4}))?\b", low)
    for m_en, mon_group, day_group, year_group in [
        (m_en1, 1, 2, 3),
        (m_en2, 2, 1, 3),
    ]:
        if not m_en:
            continue
        mon_word = m_en.group(mon_group)
        day = int(m_en.group(day_group))
        year_raw = m_en.group(year_group)
        month = next((v for k, v in EN_MONTHS.items() if mon_word.startswith(k)), None)
        if month:
            year = int(year_raw) if year_raw else base_date.year
            try:
                dt = datetime.date(year, month, day)
                if not year_raw and dt < base_date:
                    dt = datetime.date(year + 1, month, day)
                return dt
            except ValueError:
                pass

    # numeric dates dd.mm(.yyyy) or dd/mm(/yyyy)
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", segment)
    if not m:
        return None

    day = int(m.group(1))
    month = int(m.group(2))
    year_raw = m.group(3)
    year = int(year_raw) + 2000 if year_raw and len(year_raw) == 2 else int(year_raw) if year_raw else base_date.year

    try:
        dt = datetime.date(year, month, day)
        if not year_raw and dt < base_date:
            dt = datetime.date(year + 1, month, day)
        return dt
    except ValueError:
        return None


def _extract_time_from_segment(segment: str) -> datetime.time | None:
    low = segment.lower()
    m = re.search(r"(?:\bв\s*|\bat\s*)?([01]?\d|2[0-3])[:\.]([0-5]\d)\b", low)
    if m:
        return datetime.time(int(m.group(1)), int(m.group(2)))

    # allow "at 11" / "в 11"
    m2 = re.search(r"(?:\bв\s*|\bat\s*)([01]?\d|2[0-3])\b", low)
    if m2:
        return datetime.time(int(m2.group(1)), 0)
    return None


def _extract_recurrent(segment: str) -> Recurrent:
    low = segment.lower()
    if any(x in low for x in ["ежегод", "каждый год", "annual", "yearly", "every year"]):
        return Recurrent.annual
    if any(x in low for x in ["ежемесяч", "каждый месяц", "monthly", "every month"]):
        return Recurrent.monthly
    if any(x in low for x in ["еженед", "каждую неделю", "weekly", "every week"]):
        return Recurrent.weekly
    if any(x in low for x in ["ежеднев", "каждый день", "daily", "every day"]):
        return Recurrent.daily
    return Recurrent.never


def _extract_description(segment: str) -> str:
    text = re.sub(r"\s+", " ", segment).strip()
    low = text.lower()

    for marker in ["по поводу", "насчет", "на тему", "о "]:
        pos = low.find(marker)
        if pos >= 0:
            value = text[pos + len(marker) :].strip(" .,!?:;-")
            if value:
                return value

    text = re.sub(r"\b(создай|создать|добавь|добавить|запланируй|поставь|create|add|schedule|set)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b(ежегодн\w*|ежемесячн\w*|еженедельн\w*|ежедневн\w*|каждый\s+год|каждый\s+месяц|каждую\s+неделю|каждый\s+день|annual|yearly|monthly|weekly|daily|every\s+year|every\s+month|every\s+week|every\s+day)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b(сегодня|завтра|послезавтра|today|tomorrow|day after tomorrow|next)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:\bв\s*|\bat\s*)?([01]?\d|2[0-3])[:\.]([0-5]\d)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b", "", text)
    text = re.sub(r"\b(on|in)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .,!?:;-")

    return text or "Событие"


async def parse_events_from_text(text: str, user_tz: str) -> list[ParsedEvent]:
    tz = ZoneInfo(user_tz)
    base_date = datetime.datetime.now(tz).date()

    primary_chunks = [c.strip() for c in re.split(r"[\n;]+", text) if c.strip()]
    chunks: list[str] = []
    for c in primary_chunks:
        parts = re.split(
            r"\s(?:и|and)\s(?=(?:на|on|tomorrow|завтра|today|сегодня|next|следующ|\d{1,2}[./]|\d{1,2}\s+[a-zа-яё]))",
            c,
            flags=re.IGNORECASE,
        )
        chunks.extend([p.strip() for p in parts if p.strip()])

    parsed: list[ParsedEvent] = []

    for chunk in chunks:
        event_date = _extract_date_from_segment(chunk, base_date)
        event_time = _extract_time_from_segment(chunk)
        if not event_time:
            continue
        if event_date is None:
            # если дата не указана, по умолчанию считаем "завтра"
            event_date = base_date + datetime.timedelta(days=1)

        description = _extract_description(chunk)
        recurrent = _extract_recurrent(chunk)
        parsed.append(ParsedEvent(event_date=event_date, start_time=event_time, description=description, recurrent=recurrent))

    return parsed


async def _save_parsed_events(parsed_events: list[ParsedEvent], user_id: int, tz_name: str) -> int:
    created = 0
    for item in parsed_events:
        event = Event(
            event_date=item.event_date,
            description=item.description,
            start_time=item.start_time,
            recurrent=item.recurrent,
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
