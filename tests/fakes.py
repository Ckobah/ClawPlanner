from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass
class DummyMessage:
    text: str | None = None
    replies: list[dict[str, Any]] = field(default_factory=list)

    async def reply_text(self, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
        self.replies.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})


@dataclass
class DummyCallbackQuery:
    data: str
    message: DummyMessage | None = None
    from_user: Any | None = None
    answered: bool = False
    edits: list[dict[str, Any]] = field(default_factory=list)
    markup_edits: list[dict[str, Any]] = field(default_factory=list)

    async def answer(self) -> None:
        self.answered = True

    async def edit_message_text(self, text: str, reply_markup=None, parse_mode: str | None = None) -> None:
        self.edits.append({"text": text, "reply_markup": reply_markup, "parse_mode": parse_mode})

    async def edit_message_reply_markup(self, reply_markup=None) -> None:
        self.markup_edits.append({"reply_markup": reply_markup})


def make_user(user_id: int = 1, first_name: str = "Test") -> Any:
    return SimpleNamespace(id=user_id, first_name=first_name)


def make_update_with_message(
    message: DummyMessage | None = None,
    user_id: int = 1,
    first_name: str = "Test",
) -> Any:
    user = make_user(user_id=user_id, first_name=first_name)
    if message is None:
        message = DummyMessage()
    return SimpleNamespace(message=message, effective_user=user, effective_chat=user)


def make_update_with_callback(
    data: str,
    message: DummyMessage | None = None,
    user_id: int = 1,
    first_name: str = "Test",
) -> Any:
    user = make_user(user_id=user_id, first_name=first_name)
    if message is None:
        message = DummyMessage()
    callback = DummyCallbackQuery(data=data, message=message, from_user=user)
    return SimpleNamespace(callback_query=callback, effective_user=user, effective_chat=user)
