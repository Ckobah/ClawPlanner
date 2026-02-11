from __future__ import annotations

import copy
import io
import re
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any

from babel.dates import format_date, format_datetime, format_time, get_day_names
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from babel.support import NullTranslations, Translations

DEFAULT_LOCALE = "ru"
FALLBACK_LOCALE = "en"
SUPPORTED_LOCALES = {DEFAULT_LOCALE, FALLBACK_LOCALE}
LOCALES_DIR = Path(__file__).resolve().parent / "locales"
DOMAIN = "messages"


def normalize_locale(language_code: str | None, default: str = DEFAULT_LOCALE) -> str:
    if not language_code:
        return default
    normalized = language_code.replace("_", "-").lower().strip()
    primary = normalized.split("-", 1)[0]
    if primary in SUPPORTED_LOCALES:
        return primary
    return FALLBACK_LOCALE


async def resolve_user_locale(
    user_id: int | str | None,
    platform: str | None = None,
    preferred_language_code: str | None = None,
) -> str:
    if preferred_language_code:
        return normalize_locale(preferred_language_code)
    if user_id is None:
        return DEFAULT_LOCALE
    try:
        from database.db_controller import db_controller

        user = await db_controller.get_user(tg_id=int(user_id), platform=platform)
        if user and getattr(user, "language_code", None):
            return normalize_locale(user.language_code)
    except Exception:  # noqa: BLE001
        return DEFAULT_LOCALE
    return DEFAULT_LOCALE


@lru_cache(maxsize=16)
def _load_translations(locale: str) -> Translations | NullTranslations:
    po_path = LOCALES_DIR / locale / "LC_MESSAGES" / f"{DOMAIN}.po"
    if not po_path.exists():
        return NullTranslations()
    with po_path.open("r", encoding="utf-8") as po_file:
        catalog = read_po(po_file, locale=locale)
    mo_data = io.BytesIO()
    write_mo(mo_data, catalog)
    mo_data.seek(0)
    return Translations(fp=mo_data)


def _translate_dynamic(locale: str, text: str) -> str:
    if locale != "en":
        return text

    patterns: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"^✍️ Создать событие на (?P<date>\d{2}\.\d{2}\.\d{4})$"), "✍️ Create event on {date}"),
        (re.compile(r"^События на <b>(?P<date>.+)</b>:$"), "Events on <b>{date}</b>:"),
        (re.compile(r"^Вы выбрали дату: <b>(?P<date>.+)</b>$"), "You selected: <b>{date}</b>"),
        (re.compile(r"^<b>(?P<date>.+)</b>\nВыберете события для удаления:$"), "<b>{date}</b>\nSelect events to delete:"),
        (re.compile(r"^Ваш ID: (?P<user_id>.+)$"), "Your ID: {user_id}"),
        (re.compile(r"^Удалено: (?P<count>\d+)\. Выберите следующих участников\.$"), "Deleted: {count}. Choose the next participants."),
        (re.compile(r"^Удалено: (?P<count>\d+)\. Выберите новых участников\.$"), "Deleted: {count}. Choose new participants."),
        (re.compile(r"^Событие перенесено (?P<human>.+)\.$"), "Event rescheduled {human}."),
        (re.compile(r"^Пользователь (?P<name>.+) уже добавлен в ваши контакты!$"), "User {name} is already in your contacts!"),
        (re.compile(r"^Пользователь (?P<name>.+) добавлен в ваши контакты!$"), "User {name} added to your contacts!"),
    )
    for pattern, template in patterns:
        match = pattern.match(text)
        if match:
            return template.format(**match.groupdict())
    return text


def tr(text: str, locale: str | None = None) -> str:
    if not text:
        return text
    normalized_locale = normalize_locale(locale, default=DEFAULT_LOCALE)
    translated = _load_translations(normalized_locale).gettext(text)
    if translated != text:
        return translated
    if normalized_locale != DEFAULT_LOCALE:
        return _translate_dynamic(normalized_locale, text)
    return text


def trn(singular: str, plural: str, n: int, locale: str | None = None) -> str:
    normalized_locale = normalize_locale(locale, default=DEFAULT_LOCALE)
    return _load_translations(normalized_locale).ngettext(singular, plural, n)


def format_localized_date(value: date | datetime, locale: str | None = None, fmt: str = "d MMMM y") -> str:
    return format_date(value, format=fmt, locale=normalize_locale(locale))


def format_localized_time(value: time | datetime, locale: str | None = None, fmt: str = "HH:mm") -> str:
    return format_time(value, format=fmt, locale=normalize_locale(locale))


def format_localized_datetime(value: datetime, locale: str | None = None, fmt: str = "d MMMM y, HH:mm") -> str:
    return format_datetime(value, format=fmt, locale=normalize_locale(locale))


def month_year_label(year: int, month: int, locale: str | None = None) -> str:
    return format_date(date(year, month, 1), format="LLLL y", locale=normalize_locale(locale)).title()


def weekday_labels(locale: str | None = None) -> list[str]:
    normalized_locale = normalize_locale(locale)
    names = get_day_names(width="abbreviated", context="format", locale=normalized_locale)
    labels = [str(names[i]) for i in range(7)]
    if normalized_locale == "ru":
        return [item[:2].title() for item in labels]
    return labels


def translate_max_attachments(attachments: list[dict] | None, locale: str | None) -> list[dict] | None:
    if not attachments:
        return attachments
    translated = copy.deepcopy(attachments)
    for attachment in translated:
        payload = attachment.get("payload")
        if not isinstance(payload, dict):
            continue
        buttons = payload.get("buttons")
        if not isinstance(buttons, list):
            continue
        for row in buttons:
            if not isinstance(row, list):
                continue
            for button in row:
                if not isinstance(button, dict):
                    continue
                source_text = button.get("text")
                if not isinstance(source_text, str):
                    continue
                target_text = tr(source_text, locale=locale)
                button["text"] = target_text
                if button.get("type") == "message" and button.get("payload") == source_text:
                    button["payload"] = target_text
    return translated


def translate_markup(markup: Any, locale: str | None) -> Any:
    if markup is None:
        return None

    try:
        from telegram import InlineKeyboardButton as TgInlineKeyboardButton
        from telegram import InlineKeyboardMarkup as TgInlineKeyboardMarkup
        from telegram import KeyboardButton as TgKeyboardButton
        from telegram import ReplyKeyboardMarkup as TgReplyKeyboardMarkup
    except Exception:  # noqa: BLE001
        TgInlineKeyboardButton = TgInlineKeyboardMarkup = TgKeyboardButton = TgReplyKeyboardMarkup = None  # type: ignore[assignment]

    if TgInlineKeyboardMarkup and isinstance(markup, TgInlineKeyboardMarkup):
        keyboard: list[list[Any]] = []
        for row in markup.inline_keyboard:
            keyboard_row = []
            for button in row:
                data = button.to_dict()
                data["text"] = tr(str(data.get("text", "")), locale=locale)
                keyboard_row.append(TgInlineKeyboardButton(**data))
            keyboard.append(keyboard_row)
        return TgInlineKeyboardMarkup(keyboard)

    if TgReplyKeyboardMarkup and isinstance(markup, TgReplyKeyboardMarkup):
        keyboard = []
        for row in markup.keyboard:
            keyboard_row = []
            for button in row:
                data = button.to_dict()
                data["text"] = tr(str(data.get("text", "")), locale=locale)
                keyboard_row.append(TgKeyboardButton(**data))
            keyboard.append(keyboard_row)
        return TgReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=markup.resize_keyboard,
            one_time_keyboard=markup.one_time_keyboard,
            selective=markup.selective,
            input_field_placeholder=markup.input_field_placeholder,
            is_persistent=getattr(markup, "is_persistent", None),
        )

    try:
        from max_bot.compat import InlineKeyboardButton as MaxInlineKeyboardButton
        from max_bot.compat import InlineKeyboardMarkup as MaxInlineKeyboardMarkup
        from max_bot.compat import KeyboardButton as MaxKeyboardButton
        from max_bot.compat import ReplyKeyboardMarkup as MaxReplyKeyboardMarkup
    except Exception:  # noqa: BLE001
        MaxInlineKeyboardButton = MaxInlineKeyboardMarkup = MaxKeyboardButton = MaxReplyKeyboardMarkup = None  # type: ignore[assignment]

    if MaxInlineKeyboardMarkup and isinstance(markup, MaxInlineKeyboardMarkup):
        keyboard = []
        for row in markup.inline_keyboard:
            keyboard_row = []
            for button in row:
                keyboard_row.append(
                    MaxInlineKeyboardButton(
                        text=tr(button.text, locale=locale),
                        callback_data=button.callback_data,
                        url=button.url,
                        request_contact=button.request_contact,
                        request_geo_location=button.request_geo_location,
                    )
                )
            keyboard.append(keyboard_row)
        return MaxInlineKeyboardMarkup(keyboard)

    if MaxReplyKeyboardMarkup and isinstance(markup, MaxReplyKeyboardMarkup):
        keyboard = []
        for row in markup.keyboard:
            keyboard_row = []
            for button in row:
                keyboard_row.append(MaxKeyboardButton(text=tr(button.text, locale=locale), request_location=button.request_location))
            keyboard.append(keyboard_row)
        return MaxReplyKeyboardMarkup(
            keyboard=keyboard,
            resize_keyboard=markup.resize_keyboard,
            one_time_keyboard=markup.one_time_keyboard,
        )

    return markup
