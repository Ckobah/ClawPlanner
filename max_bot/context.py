from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from i18n import resolve_user_locale, tr, translate_markup
from max_bot.client import MaxApi
from max_bot.compat import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

logger = logging.getLogger(__name__)


@dataclass
class MaxChat:
    id: str | int
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    is_bot: bool | None = None
    type: str = "private"

    @property
    def full_name(self) -> str:
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.last_name or str(self.id)


@dataclass
class MaxMessage:
    id: str | int
    text: str | None
    location: dict | None
    contact: dict | None
    attachments: list[dict] | None
    sender: MaxChat
    recipient: MaxChat | None
    bot: MaxApi

    @property
    def message_id(self) -> str | int:
        return self.id

    @property
    def chat_id(self) -> int:
        if self.recipient and self.recipient.is_bot is False:
            return self.recipient.id
        if self.sender and self.sender.is_bot is False:
            return self.sender.id
        return self.recipient.id if self.recipient else self.sender.id

    async def reply_text(
        self,
        text: str,
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
        parse_mode: str | None = None,
        include_menu: bool = True,
    ) -> "MaxMessage | None":
        if self.recipient and self.recipient.is_bot is False:
            target_user_id = self.recipient.id
        elif self.sender and self.sender.is_bot is False:
            target_user_id = self.sender.id
        else:
            target_user_id = self.recipient.id if self.recipient else self.sender.id

        locale = await resolve_user_locale(target_user_id, platform="max")

        if include_menu:
            menu_text = tr("Меню", locale)
            menu_callback = "menu_open"
            if reply_markup is None:
                reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(menu_text, callback_data=menu_callback)]])
            elif isinstance(reply_markup, InlineKeyboardMarkup):
                has_menu = any(
                    btn.text in {menu_text, "Меню", "Menu"} and (btn.callback_data == menu_callback or btn.callback_data is None)
                    for row in reply_markup.inline_keyboard
                    for btn in row
                )
                if not has_menu:
                    reply_markup.inline_keyboard.append([InlineKeyboardButton(menu_text, callback_data=menu_callback)])
            elif isinstance(reply_markup, ReplyKeyboardMarkup):
                has_menu = any(btn.text in {menu_text, "Меню", "Menu"} for row in reply_markup.keyboard for btn in row)
                if not has_menu:
                    reply_markup.keyboard.append([KeyboardButton(menu_text)])

        reply_markup = translate_markup(reply_markup, locale)
        attachments = None
        if reply_markup:
            attachments = reply_markup.to_attachments()
        fmt = None
        if parse_mode == "HTML":
            fmt = "html"
        response = await self.bot.send_message(
            text=tr(text, locale),
            user_id=target_user_id,
            attachments=attachments,
            fmt=fmt,
            include_menu=include_menu,
            locale=locale,
        )
        message_data = response.get("message") if isinstance(response, dict) else None
        if not message_data:
            return None
        body = message_data.get("body") or {}
        message_id = message_data.get("id") or message_data.get("message_id") or body.get("mid") or body.get("message_id") or 0
        return MaxMessage(
            id=message_id,
            text=text,
            location=None,
            contact=None,
            attachments=attachments,
            sender=self.sender,
            recipient=self.recipient,
            bot=self.bot,
        )


@dataclass
class MaxCallbackQuery:
    data: str
    message: MaxMessage
    from_user: MaxChat
    bot: MaxApi

    async def answer(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def edit_message_text(self, text: str, reply_markup: InlineKeyboardMarkup | None = None, parse_mode: str | None = None) -> None:
        locale = await resolve_user_locale(getattr(self.from_user, "id", None), platform="max")
        fmt = None
        if parse_mode == "HTML":
            fmt = "html"
        await self.bot.edit_message(
            message_id=self.message.id,
            text=tr(text, locale),
            attachments=translate_markup(reply_markup, locale).to_attachments() if reply_markup else [],
            fmt=fmt,
            locale=locale,
        )

    async def edit_message_reply_markup(self, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        locale = await resolve_user_locale(getattr(self.from_user, "id", None), platform="max")
        translated = translate_markup(reply_markup, locale)
        attachments = translated.to_attachments() if translated else []
        await self.bot.edit_message(message_id=self.message.id, attachments=attachments, locale=locale)


@dataclass
class MaxUpdate:
    message: MaxMessage | None = None
    callback_query: MaxCallbackQuery | None = None

    @property
    def effective_chat(self) -> MaxChat | None:
        if self.callback_query:
            return self.callback_query.from_user
        if self.message:
            return self.message.sender
        return None

    @property
    def effective_user(self) -> MaxChat | None:
        return self.effective_chat


@dataclass
class MaxContext:
    bot: MaxApi
    chat_data: dict[str, Any] = field(default_factory=dict)
