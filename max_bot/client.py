import asyncio
import logging
from typing import Any

import httpx

from config import MAX_API_BASE, MAX_BOT_TOKEN
from i18n import resolve_user_locale, tr, translate_max_attachments

logger = logging.getLogger(__name__)


class MaxApi:
    def __init__(self, token: str | None = None, base_url: str | None = None) -> None:
        if not token:
            raise ValueError("MAX_BOT_TOKEN is required")
        self._token = token
        self._base_url = base_url or MAX_API_BASE
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=40.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, params: dict | None = None, payload: dict | None = None) -> dict:
        headers = {"Authorization": self._token}
        response = await self._client.request(method, path, params=params, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.exception(
                "MAX API error %s %s: %s | params=%s payload=%s",
                method,
                path,
                response.text,
                params,
                payload,
            )
            raise
        return response.json() if response.text else {}

    async def get_updates(
        self,
        marker: str | None = None,
        limit: int = 100,
        timeout: int = 30,
        types: list[str] | None = None,
    ) -> dict:
        params: dict[str, Any] = {
            "limit": limit,
            "timeout": timeout,
        }
        if marker:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        return await self.request("GET", "/updates", params=params)

    async def create_subscription(
        self,
        url: str,
        update_types: list[str] | None = None,
        secret: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"url": url}
        if update_types:
            payload["update_types"] = update_types
        if secret:
            payload["secret"] = secret
        return await self.request("POST", "/subscriptions", payload=payload)

    async def delete_subscription(self, url: str) -> dict:
        params = {"url": url}
        return await self.request("DELETE", "/subscriptions", params=params)

    async def send_message(
        self,
        text: str,
        user_id: int | None = None,
        chat_id: int | None = None,
        attachments: list[dict] | None = None,
        fmt: str | None = None,
        notify: bool | None = True,
        disable_link_preview: bool | None = None,
        include_menu: bool = True,
        locale: str | None = None,
    ) -> dict:
        if locale is None:
            locale = await resolve_user_locale(user_id or chat_id, platform="max")

        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        if chat_id is not None:
            params["chat_id"] = chat_id
        if disable_link_preview is not None:
            params["disable_link_preview"] = disable_link_preview

        if include_menu:
            menu_text = tr("Меню", locale)
            menu_payload = "menu_open"
            menu_button = {"type": "callback", "text": menu_text, "payload": menu_payload}
            if attachments is None:
                attachments = [{"type": "inline_keyboard", "payload": {"buttons": [[menu_button]]}}]
            else:
                inline_keyboard = None
                for att in attachments:
                    if att.get("type") == "inline_keyboard":
                        inline_keyboard = att
                        break
                if inline_keyboard is None:
                    attachments.append({"type": "inline_keyboard", "payload": {"buttons": [[menu_button]]}})
                else:
                    payload = inline_keyboard.setdefault("payload", {})
                    buttons = payload.setdefault("buttons", [])
                    has_menu = any(btn.get("payload") == menu_payload for row in buttons for btn in row)
                    if not has_menu:
                        buttons.append([menu_button])

        translated_attachments = translate_max_attachments(attachments, locale)
        payload: dict[str, Any] = {"text": tr(text, locale)}
        if translated_attachments is not None:
            payload["attachments"] = translated_attachments
        if fmt:
            payload["format"] = fmt
        if notify is not None:
            payload["notify"] = notify

        return await self.request("POST", "/messages", params=params, payload=payload)

    async def edit_message(
        self,
        message_id: str | int,
        text: str | None = None,
        attachments: list[dict] | None = None,
        fmt: str | None = None,
        notify: bool | None = True,
        locale: str | None = None,
    ) -> dict:
        params = {"message_id": message_id}
        payload: dict[str, Any] = {}
        if text is not None:
            payload["text"] = tr(text, locale)
        if attachments is not None:
            payload["attachments"] = translate_max_attachments(attachments, locale)
        if fmt:
            payload["format"] = fmt
        if notify is not None:
            payload["notify"] = notify

        return await self.request("PUT", "/messages", params=params, payload=payload)

    async def delete_message(self, message_id: str | int) -> dict:
        params = {"message_id": message_id}
        return await self.request("DELETE", "/messages", params=params)


async def build_max_api() -> MaxApi:
    await asyncio.sleep(0)
    return MaxApi(token=MAX_BOT_TOKEN, base_url=MAX_API_BASE)
