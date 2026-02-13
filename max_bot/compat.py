from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InlineKeyboardButton:
    text: str
    callback_data: str | None = None
    url: str | None = None
    request_contact: bool = False
    request_geo_location: bool = False

    def to_payload(self) -> dict[str, Any]:
        if self.url:
            return {"type": "link", "text": self.text, "url": self.url}
        if self.request_contact:
            return {"type": "request_contact", "text": self.text}
        if self.request_geo_location:
            return {"type": "request_geo_location", "text": self.text}
        if self.callback_data is None:
            return {"type": "message", "text": self.text, "payload": self.text}
        return {"type": "callback", "text": self.text, "payload": self.callback_data}


@dataclass
class InlineKeyboardMarkup:
    inline_keyboard: list[list[InlineKeyboardButton]] = field(default_factory=list)

    def to_attachments(self) -> list[dict[str, Any]]:
        buttons = [[btn.to_payload() for btn in row] for row in self.inline_keyboard]
        return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]


@dataclass
class KeyboardButton:
    text: str
    request_location: bool = False


@dataclass
class ReplyKeyboardMarkup:
    keyboard: list[list[KeyboardButton]]
    resize_keyboard: bool = False
    one_time_keyboard: bool = False

    def to_attachments(self) -> list[dict[str, Any]]:
        buttons: list[list[dict[str, Any]]] = []
        for row in self.keyboard:
            row_buttons: list[dict[str, Any]] = []
            for btn in row:
                if btn.request_location:
                    row_buttons.append({"type": "request_geo_location", "text": btn.text})
                else:
                    row_buttons.append({"type": "message", "text": btn.text, "payload": btn.text})
            buttons.append(row_buttons)
        return [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]
