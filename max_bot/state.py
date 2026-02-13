from __future__ import annotations

from collections import defaultdict
from typing import Any


class ChatState:
    def __init__(self) -> None:
        self._data: dict[int, dict[str, Any]] = defaultdict(dict)

    def get(self, chat_id: int) -> dict[str, Any]:
        return self._data[chat_id]


chat_state = ChatState()
