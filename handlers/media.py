import asyncio
import datetime
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import fitz
from pypdf import PdfReader
from rapidocr_onnxruntime import RapidOCR
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import WHISPER_LANGUAGE, WHISPER_MODEL
from database.db_controller import db_controller
from entities import Event, Recurrent
from i18n import resolve_user_locale, tr

logger = logging.getLogger(__name__)

OPENCLAW_BIN = os.getenv("OPENCLAW_BIN") or shutil.which("openclaw") or "/home/clawd/.npm-global/bin/openclaw"
AI_TIMEOUT_SECONDS = int(os.getenv("AI_TIMEOUT_SECONDS", "90"))

_whisper_model = None
_ocr_engine = None


@dataclass
class ParsedEvent:
    event_date: datetime.date
    start_time: datetime.time
    stop_time: datetime.time | None = None
    description: str = "Событие"
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


def _extract_time_range_from_segment(segment: str) -> tuple[datetime.time | None, datetime.time | None]:
    low = segment.lower()

    # 11:00-12:30 / 11.00 - 12.30
    m_range = re.search(r"([01]?\d|2[0-3])[:\.]([0-5]\d)\s*[-–—]\s*([01]?\d|2[0-3])[:\.]([0-5]\d)", low)
    if m_range:
        start = datetime.time(int(m_range.group(1)), int(m_range.group(2)))
        stop = datetime.time(int(m_range.group(3)), int(m_range.group(4)))
        return start, stop

    # с 11:00 до 12:30 / from 11:00 to 12:30
    m_from_to = re.search(
        r"(?:с|from)\s*([01]?\d|2[0-3])[:\.]([0-5]\d)\s*(?:до|to|till|until)\s*([01]?\d|2[0-3])[:\.]([0-5]\d)",
        low,
    )
    if m_from_to:
        start = datetime.time(int(m_from_to.group(1)), int(m_from_to.group(2)))
        stop = datetime.time(int(m_from_to.group(3)), int(m_from_to.group(4)))
        return start, stop

    # single time
    m = re.search(r"(?:\bв\s*|\bat\s*)?([01]?\d|2[0-3])[:\.]([0-5]\d)\b", low)
    if m:
        return datetime.time(int(m.group(1)), int(m.group(2))), None

    # allow "at 11" / "в 11"
    m2 = re.search(r"(?:\bв\s*|\bat\s*)([01]?\d|2[0-3])\b", low)
    if m2:
        return datetime.time(int(m2.group(1)), 0), None

    return None, None


def _extract_recurrent(segment: str) -> Recurrent:
    low = segment.lower()

    annual_markers = [
        "ежегод", "ежегодно", "каждый год", "раз в год", "годовщин", "annual", "yearly", "every year", "once a year",
    ]
    monthly_markers = [
        "ежемесяч", "ежемесячно", "каждый месяц", "раз в месяц", "monthly", "every month", "once a month",
    ]
    weekly_markers = [
        "еженед", "еженедельно", "каждую неделю", "каждой неделе", "раз в неделю", "weekly", "every week", "once a week",
    ]
    daily_markers = [
        "ежеднев", "ежедневно", "каждый день", "каждыйдень", "раз в день", "daily", "every day", "once a day",
    ]

    if any(x in low for x in annual_markers):
        return Recurrent.annual
    if any(x in low for x in monthly_markers):
        return Recurrent.monthly
    if any(x in low for x in weekly_markers):
        return Recurrent.weekly
    if any(x in low for x in daily_markers):
        return Recurrent.daily

    # "каждый понедельник" / "every monday" => weekly
    weekday_ru = ["понедельник", "вторник", "сред", "четверг", "пятниц", "суббот", "воскресень"]
    weekday_en = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if ("каждый" in low and any(w in low for w in weekday_ru)) or ("every" in low and any(w in low for w in weekday_en)):
        return Recurrent.weekly

    return Recurrent.never


def _extract_best_title_from_text(text: str) -> str | None:
    lines = [re.sub(r"\s+", " ", ln).strip(" -—|\t") for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return None

    blacklist = [
        "январ", "феврал", "март", "апрел", "мая", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр",
        "today", "tomorrow", "вход", "билет", "место", "ряд", "дата", "время", "адрес", "дворец культуры",
    ]

    candidates: list[str] = []
    for ln in lines:
        low = ln.lower()
        if re.search(r"\b\d{1,2}[:\.]\d{2}\b", low):
            continue
        if re.search(r"\b\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?\b", low):
            continue
        if any(b in low for b in blacklist):
            continue
        if len(ln) < 8:
            continue
        candidates.append(ln)

    if not candidates:
        return None

    # обычно заголовок афиши — самая длинная «смысловая» строка
    best = max(candidates, key=len)
    return best[:160]


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


async def parse_events_from_text(text: str, user_tz: str, default_date_if_missing: bool = True) -> list[ParsedEvent]:
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
        start_time, stop_time = _extract_time_range_from_segment(chunk)
        if not start_time:
            continue
        if event_date is None:
            if not default_date_if_missing:
                continue
            # если дата не указана, по умолчанию считаем "завтра"
            event_date = base_date + datetime.timedelta(days=1)

        description = _extract_description(chunk)
        recurrent = _extract_recurrent(chunk)
        parsed.append(
            ParsedEvent(
                event_date=event_date,
                start_time=start_time,
                stop_time=stop_time,
                description=description,
                recurrent=recurrent,
            )
        )

    return parsed


def _extract_ticket_event_hint(text: str, user_tz: str) -> list[ParsedEvent]:
    low = text.lower()
    ticket_markers = ["билет", "партер", "ряд", "место", "клуб", "ticket", "seat", "row"]
    if not any(m in low for m in ticket_markers):
        return []

    tz = ZoneInfo(user_tz)
    base_date = datetime.datetime.now(tz).date()

    # try to find event-like date with month words + time
    ru_month_regex = r"(январ[яь]|феврал[яь]|март[а]?|апрел[яь]|мая|июн[яь]|июл[яь]|август[а]?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])"
    m = re.search(rf"\b(\d{{1,2}})\s+{ru_month_regex}\s+([01]?\d|2[0-3])[:\.]([0-5]\d)\b", low)
    if not m:
        return []

    day = int(m.group(1))
    mon_word = m.group(2)
    month = next((v for k, v in RU_MONTHS.items() if mon_word.startswith(k)), None)
    if not month:
        return []

    hour = int(m.group(3))
    minute = int(m.group(4))

    year = base_date.year
    event_date = datetime.date(year, month, day)
    # allow near-past tickets (up to 30 days) to avoid wrong year rollover
    if event_date < base_date - datetime.timedelta(days=30):
        event_date = datetime.date(year + 1, month, day)

    # venue/address extraction
    venue = ""
    m_venue = re.search(r"(клуб[^;\n]+)", text, flags=re.IGNORECASE)
    if m_venue:
        venue = m_venue.group(1).strip()
    m_addr = re.search(r"(москва[^\n]+)", text, flags=re.IGNORECASE)
    addr = m_addr.group(1).strip() if m_addr else ""

    desc = "Мероприятие по билету"
    if venue:
        desc = venue
    if addr:
        desc = f"{desc} | {addr}"

    return [
        ParsedEvent(
            event_date=event_date,
            start_time=datetime.time(hour, minute),
            stop_time=None,
            description=desc,
            recurrent=Recurrent.never,
        )
    ]


def _extract_json_array(raw: str) -> list[dict]:
    if not raw:
        return []
    text = raw.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE | re.DOTALL)

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        pass

    m = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        return []
    return []


async def _extract_events_with_openclaw(text: str, user_tz: str, locale: str | None = None, user_id: int | None = None) -> list[ParsedEvent]:
    prompt = (
        "Извлеки события из текста/афиши. Верни только JSON-массив без пояснений. "
        "Каждый объект: date(YYYY-MM-DD), start_time(HH:MM), end_time(HH:MM|null), description, address, recurrent(one of: never,daily,weekly,monthly,annual). "
        f"Часовой пояс пользователя: {user_tz}. "
        "Если год не указан, выбери ближайшую будущую дату. Если это билет/афиша — постарайся правильно извлечь дату, время и адрес.\n\n"
        f"Текст:\n{text}"
    )

    session_id = f"tg_planner_media_extract_{user_id or 'shared'}"
    cmd = (
        f"export PATH=/home/clawd/.npm-global/bin:$PATH; "
        f"{shlex.quote(OPENCLAW_BIN)} agent --session-id {shlex.quote(session_id)} --message {shlex.quote(prompt)} --json --timeout {AI_TIMEOUT_SECONDS}"
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            f"/bin/bash -lc {shlex.quote(cmd)}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except Exception:
        logger.exception("openclaw extract launch failed")
        return []

    if proc.returncode != 0:
        logger.error("openclaw extract failed rc=%s stderr=%s", proc.returncode, stderr.decode("utf-8", errors="ignore").strip())
        return []

    try:
        payload = json.loads(stdout.decode("utf-8", errors="ignore"))
        result = (payload.get("result") or {}) if isinstance(payload, dict) else {}
        parts = result.get("payloads") or []
        text_out = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except Exception:
        logger.exception("openclaw extract parse failed")
        return []

    rows = _extract_json_array(text_out)
    parsed: list[ParsedEvent] = []
    for row in rows:
        try:
            d = datetime.date.fromisoformat(str(row.get("date", "")).strip())
            st = datetime.time.fromisoformat(str(row.get("start_time", "")).strip())
        except Exception:
            continue

        end_raw = row.get("end_time")
        stop_time = None
        if end_raw:
            try:
                stop_time = datetime.time.fromisoformat(str(end_raw).strip())
            except Exception:
                stop_time = None

        rec_raw = str(row.get("recurrent", "never")).strip().lower()
        recurrent = Recurrent.never
        rec_map = {
            "never": Recurrent.never,
            "daily": Recurrent.daily,
            "weekly": Recurrent.weekly,
            "monthly": Recurrent.monthly,
            "annual": Recurrent.annual,
            "ежедневно": Recurrent.daily,
            "еженедельно": Recurrent.weekly,
            "ежемесячно": Recurrent.monthly,
            "ежегодно": Recurrent.annual,
        }
        recurrent = rec_map.get(rec_raw, recurrent)

        description = (str(row.get("description", "")).strip() or "Событие")
        address = str(row.get("address", "")).strip()
        if address:
            description = f"{description} | Адрес: {address}"

        parsed.append(ParsedEvent(event_date=d, start_time=st, stop_time=stop_time, description=description, recurrent=recurrent))

    return parsed


async def _save_parsed_events(parsed_events: list[ParsedEvent], user_id: int, tz_name: str) -> int:
    created = 0
    for item in parsed_events:
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
    return created


def _serialize_parsed_events(parsed_events: list[ParsedEvent]) -> list[dict[str, str | None]]:
    payload: list[dict[str, str | None]] = []
    for item in parsed_events:
        payload.append(
            {
                "date": item.event_date.isoformat(),
                "start_time": item.start_time.strftime("%H:%M"),
                "end_time": item.stop_time.strftime("%H:%M") if item.stop_time else None,
                "description": item.description,
                "recurrent": item.recurrent.value if isinstance(item.recurrent, Recurrent) else str(item.recurrent),
            }
        )
    return payload


def _deserialize_parsed_events(payload: list[dict]) -> list[ParsedEvent]:
    parsed: list[ParsedEvent] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            d = datetime.date.fromisoformat(str(row.get("date", "")).strip())
            st = datetime.time.fromisoformat(str(row.get("start_time", "")).strip())
        except Exception:
            continue

        end_raw = row.get("end_time")
        stop_time = None
        if end_raw:
            try:
                stop_time = datetime.time.fromisoformat(str(end_raw).strip())
            except Exception:
                stop_time = None

        rec_raw = str(row.get("recurrent", "never")).strip().lower()
        recurrent = Recurrent.never
        rec_map = {
            "never": Recurrent.never,
            "daily": Recurrent.daily,
            "weekly": Recurrent.weekly,
            "monthly": Recurrent.monthly,
            "annual": Recurrent.annual,
            "ежедневно": Recurrent.daily,
            "еженедельно": Recurrent.weekly,
            "ежемесячно": Recurrent.monthly,
            "ежегодно": Recurrent.annual,
        }
        recurrent = rec_map.get(rec_raw, recurrent)

        description = str(row.get("description", "")).strip() or "Событие"
        parsed.append(ParsedEvent(event_date=d, start_time=st, stop_time=stop_time, description=description, recurrent=recurrent))
    return parsed


def _event_preview_lines(parsed_events: list[ParsedEvent]) -> list[str]:
    lines: list[str] = []
    for idx, item in enumerate(parsed_events, start=1):
        desc = item.description or "Событие"
        venue = None
        note = None
        if "| Адрес:" in desc:
            main_desc, addr = desc.split("| Адрес:", 1)
            desc = main_desc.strip() or "Событие"
            venue = addr.strip() or None

        time_text = item.start_time.strftime("%H:%M")
        if item.stop_time:
            time_text = f"{time_text}–{item.stop_time.strftime('%H:%M')}"

        lines.append(f"Событие #{idx}")
        lines.append(f"- Дата: {item.event_date.strftime('%d.%m.%Y')}")
        lines.append(f"- Время: {time_text}")
        lines.append(f"- Описание: {desc}")
        if venue:
            lines.append(f"- Место: {venue}")
        if note:
            lines.append(f"- Примечание: {note}")
        lines.append("")

    return lines[:-1] if lines and lines[-1] == "" else lines


async def _ask_confirmation_for_events(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parsed_events: list[ParsedEvent],
    locale: str | None,
    source_text: str,
    tz_name: str,
) -> None:
    if not update.message:
        return

    context.chat_data["pending_event_confirmation"] = {
        "events": _serialize_parsed_events(parsed_events),
        "source_text": source_text,
        "user_tz": tz_name,
    }

    lines = [tr("Проверь, всё ли верно перед сохранением:", locale), ""]
    lines.extend(_event_preview_lines(parsed_events))

    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Сохранить", callback_data="media_confirm_save")], [InlineKeyboardButton("✏️ Исправить", callback_data="media_confirm_edit")]]
    )
    await update.message.reply_text("\n".join(lines), reply_markup=markup)


def _parse_openclaw_smart_payload(raw: str) -> tuple[list[ParsedEvent], str | None]:
    if not raw:
        return [], None

    text = raw.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE | re.DOTALL)

    try:
        payload = json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return [], None
        try:
            payload = json.loads(m.group(0))
        except Exception:
            return [], None

    if not isinstance(payload, dict):
        return [], None

    status = str(payload.get("status", "")).strip().lower()
    if status == "clarify":
        q = str(payload.get("question", "")).strip()
        return [], (q or None)

    rows = payload.get("events")
    if not isinstance(rows, list):
        return [], None

    parsed: list[ParsedEvent] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            d = datetime.date.fromisoformat(str(row.get("date", "")).strip())
            st = datetime.time.fromisoformat(str(row.get("start_time", "")).strip())
        except Exception:
            continue

        end_raw = row.get("end_time")
        stop_time = None
        if end_raw:
            try:
                stop_time = datetime.time.fromisoformat(str(end_raw).strip())
            except Exception:
                stop_time = None

        rec_raw = str(row.get("recurrent", "never")).strip().lower()
        recurrent = Recurrent.never
        rec_map = {
            "never": Recurrent.never,
            "daily": Recurrent.daily,
            "weekly": Recurrent.weekly,
            "monthly": Recurrent.monthly,
            "annual": Recurrent.annual,
            "ежедневно": Recurrent.daily,
            "еженедельно": Recurrent.weekly,
            "ежемесячно": Recurrent.monthly,
            "ежегодно": Recurrent.annual,
        }
        recurrent = rec_map.get(rec_raw, recurrent)

        description = (str(row.get("description", "")).strip() or "Событие")
        address = str(row.get("address", "")).strip()
        if address:
            description = f"{description} | Адрес: {address}"

        parsed.append(ParsedEvent(event_date=d, start_time=st, stop_time=stop_time, description=description, recurrent=recurrent))

    return parsed, None


async def _extract_events_or_clarify_with_openclaw(text: str, user_tz: str, user_id: int | None = None) -> tuple[list[ParsedEvent], str | None]:
    prompt = (
        "Используй навык smart-event-ingest, если он доступен. "
        "Ты извлекаешь события из OCR/голосового текста для календаря. "
        "Верни СТРОГО JSON-объект БЕЗ пояснений. "
        "Если данных достаточно: {\"status\":\"ok\",\"events\":[{date,start_time,end_time,description,address,recurrent}]}. "
        "Если данных недостаточно/двусмысленно: {\"status\":\"clarify\",\"question\":\"...\"}. "
        "date=YYYY-MM-DD, time=HH:MM, recurrent in never|daily|weekly|monthly|annual. "
        "Часовой пояс пользователя: " + user_tz + ".\n\n"
        "Текст:\n" + text
    )

    session_id = f"tg_planner_media_extract_{user_id or 'shared'}"
    cmd = (
        f"export PATH=/home/clawd/.npm-global/bin:$PATH; "
        f"{shlex.quote(OPENCLAW_BIN)} agent --session-id {shlex.quote(session_id)} --message {shlex.quote(prompt)} --json --timeout {AI_TIMEOUT_SECONDS}"
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            f"/bin/bash -lc {shlex.quote(cmd)}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except Exception:
        logger.exception("openclaw smart extract launch failed")
        return [], None

    if proc.returncode != 0:
        logger.error("openclaw smart extract failed rc=%s stderr=%s", proc.returncode, stderr.decode("utf-8", errors="ignore").strip())
        return [], None

    try:
        payload = json.loads(stdout.decode("utf-8", errors="ignore"))
        result = (payload.get("result") or {}) if isinstance(payload, dict) else {}
        parts = result.get("payloads") or []
        text_out = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))
    except Exception:
        logger.exception("openclaw smart extract parse failed")
        return [], None

    return _parse_openclaw_smart_payload(text_out)


async def _process_extracted_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> bool:
    if not update.message or not update.effective_chat:
        return False

    locale = await resolve_user_locale(update.effective_chat.id, platform="tg")
    user = await db_controller.get_user(update.effective_chat.id, platform="tg")
    tz_name = (getattr(user, "time_zone", None) or "Europe/Moscow") if user else "Europe/Moscow"

    parsed_events = _extract_ticket_event_hint(text, user_tz=tz_name)
    if not parsed_events:
        parsed_events = await _extract_events_with_openclaw(
            text,
            user_tz=tz_name,
            locale=locale,
            user_id=update.effective_chat.id,
        )
    if not parsed_events:
        parsed_events = await parse_events_from_text(text, user_tz=tz_name, default_date_if_missing=False)

    fallback_title = _extract_best_title_from_text(text)

    # sanity filter: remove obvious garbage/duplicates
    unique = {}
    for ev in parsed_events:
        if not ev.description or ev.description.isdigit():
            continue

        if ev.description.strip().lower() in {"событие", "event"} and fallback_title:
            ev.description = fallback_title

        key = (ev.event_date.isoformat(), ev.start_time.strftime("%H:%M"), ev.description.strip().lower())
        unique[key] = ev
    parsed_events = list(unique.values())

    if not parsed_events:
        smart_events, clarify_question = await _extract_events_or_clarify_with_openclaw(
            text=text,
            user_tz=tz_name,
            user_id=update.effective_chat.id,
        )
        if smart_events:
            parsed_events = smart_events
        elif clarify_question:
            context.chat_data["pending_event_clarification"] = {
                "base_text": text,
                "user_tz": tz_name,
                "attempts": 1,
            }
            await update.message.reply_text(clarify_question)
            return True
        else:
            await update.message.reply_text(
                tr("Не смог уверенно выделить события из файла/голоса. Пришли текстом дату/время/описание или более четкий PDF.", locale)
            )
            return True

    await _ask_confirmation_for_events(
        update=update,
        context=context,
        parsed_events=parsed_events,
        locale=locale,
        source_text=text,
        tz_name=tz_name,
    )
    return True


async def handle_pending_event_clarification(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.effective_chat:
        return False

    pending = context.chat_data.get("pending_event_clarification")
    if not pending:
        return False

    locale = await resolve_user_locale(update.effective_chat.id, platform="tg")
    user = await db_controller.get_user(update.effective_chat.id, platform="tg")
    tz_name = (getattr(user, "time_zone", None) or "Europe/Moscow") if user else "Europe/Moscow"

    base_text = str(pending.get("base_text", ""))
    answer_text = (update.message.text or "").strip()
    merged_text = f"{base_text}\n\nУточнение пользователя: {answer_text}"

    parsed_events, clarify_question = await _extract_events_or_clarify_with_openclaw(
        text=merged_text,
        user_tz=tz_name,
        user_id=update.effective_chat.id,
    )
    if not parsed_events:
        parsed_events = await _extract_events_with_openclaw(
            text=merged_text,
            user_tz=tz_name,
            locale=locale,
            user_id=update.effective_chat.id,
        )
    if not parsed_events:
        parsed_events = await parse_events_from_text(merged_text, user_tz=tz_name, default_date_if_missing=False)

    fallback_title = _extract_best_title_from_text(merged_text)
    unique = {}
    for ev in parsed_events:
        if not ev.description or ev.description.isdigit():
            continue
        if ev.description.strip().lower() in {"событие", "event"} and fallback_title:
            ev.description = fallback_title
        key = (ev.event_date.isoformat(), ev.start_time.strftime("%H:%M"), ev.description.strip().lower())
        unique[key] = ev
    parsed_events = list(unique.values())

    if parsed_events:
        context.chat_data.pop("pending_event_clarification", None)
        await _ask_confirmation_for_events(
            update=update,
            context=context,
            parsed_events=parsed_events,
            locale=locale,
            source_text=merged_text,
            tz_name=tz_name,
        )
        return True

    attempts = int(pending.get("attempts", 1)) + 1
    pending["attempts"] = attempts
    pending["base_text"] = merged_text
    context.chat_data["pending_event_clarification"] = pending

    if clarify_question:
        await update.message.reply_text(clarify_question)
    else:
        await update.message.reply_text(
            tr("Нужно чуть больше деталей. Напиши, пожалуйста: дату, время и короткое описание события.", locale)
        )
    return True


async def handle_media_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_chat:
        return

    await query.answer()
    locale = await resolve_user_locale(update.effective_chat.id, platform="tg")
    pending = context.chat_data.get("pending_event_confirmation")
    if not pending:
        await query.edit_message_text(tr("Черновик события не найден. Отправь файл/голос ещё раз.", locale))
        return

    data = query.data or ""
    if data == "media_confirm_save":
        user = await db_controller.get_user(update.effective_chat.id, platform="tg")
        tz_name = str(pending.get("user_tz") or (getattr(user, "time_zone", None) or "Europe/Moscow"))
        events_payload = pending.get("events") or []
        parsed_events = _deserialize_parsed_events(events_payload)
        if not parsed_events:
            await query.edit_message_text(tr("Не получилось прочитать черновик. Пришли файл заново.", locale))
            return

        created = await _save_parsed_events(parsed_events, user_id=update.effective_chat.id, tz_name=tz_name)
        context.chat_data.pop("pending_event_confirmation", None)
        if not created:
            await query.edit_message_text(tr("Не получилось записать события в календарь.", locale))
            return

        lines = [tr("Добавил событий: {count}", locale).format(count=created)]
        for item in parsed_events[:10]:
            lines.append(f"• {item.event_date.strftime('%d.%m.%Y')} {item.start_time.strftime('%H:%M')} — {item.description}")
        await query.edit_message_text("\n".join(lines))
        return

    if data == "media_confirm_edit":
        source_text = str(pending.get("source_text", "")).strip()
        user_tz = str(pending.get("user_tz", "Europe/Moscow"))
        context.chat_data["pending_event_clarification"] = {
            "base_text": source_text,
            "user_tz": user_tz,
            "attempts": 1,
        }
        context.chat_data.pop("pending_event_confirmation", None)
        await query.edit_message_text(
            tr("Ок, что исправить? Напиши в одном сообщении дату, время, описание и (если есть) место.", locale)
        )
        return


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

    await _process_extracted_text(update, context, text)


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

    await _process_extracted_text(update, context, text)


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

    await _process_extracted_text(update, context, text)
