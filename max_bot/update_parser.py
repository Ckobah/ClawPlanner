import logging
from typing import Any

from max_bot.client import MaxApi
from max_bot.context import MaxCallbackQuery, MaxChat, MaxMessage, MaxUpdate

logger = logging.getLogger(__name__)


def _parse_user(data: dict | None) -> MaxChat:
    if not data:
        return MaxChat(id=0, first_name=None, last_name=None)
    user_id = data.get("id") or data.get("user_id") or 0
    first_name = data.get("name") or data.get("first_name")
    last_name = data.get("last_name")
    language_code = data.get("language_code") or data.get("locale")
    is_bot = data.get("is_bot")
    return MaxChat(id=int(user_id), first_name=first_name, last_name=last_name, language_code=language_code, is_bot=is_bot)


def _parse_message(data: dict | None, api: MaxApi) -> MaxMessage | None:
    if not data:
        return None
    body = data.get("body") or {}
    message_id = data.get("id") or data.get("message_id") or body.get("mid") or body.get("message_id") or 0
    text = body.get("text")
    location = None
    contact = None
    attachments = body.get("attachments") or data.get("attachments") or []
    for attachment in attachments:
        att_type = attachment.get("type")
        payload = attachment.get("payload") or attachment.get("body") or {}
        if att_type in {"contact", "shared_contact", "user_contact"} and not payload:
            payload = attachment
        if att_type in {"contact", "shared_contact", "user_contact"} and isinstance(payload, dict) and payload.get("max_info"):
            payload = payload.get("max_info") or payload
        lat = attachment.get("lat") or attachment.get("latitude")
        lon = attachment.get("lon") or attachment.get("longitude")
        if lat is not None and lon is not None:
            location = {"latitude": lat, "longitude": lon}
            break
        lat = payload.get("lat") or payload.get("latitude")
        lon = payload.get("lon") or payload.get("longitude")
        if lat is not None and lon is not None:
            location = {"latitude": lat, "longitude": lon}
            break
        if att_type not in {"geo_location", "location", "geolocation", "geo", "shared_location"}:
            if att_type in {"contact", "shared_contact", "user_contact"} or payload.get("phone") or payload.get("phone_number"):
                contact = {
                    "user_id": payload.get("user_id") or payload.get("id"),
                    "first_name": payload.get("first_name") or payload.get("name"),
                    "last_name": payload.get("last_name"),
                    "phone_number": payload.get("phone_number") or payload.get("phone"),
                }
            continue
        lat = payload.get("lat") or payload.get("latitude")
        lon = payload.get("lon") or payload.get("longitude")
        if lat is not None and lon is not None:
            location = {"latitude": lat, "longitude": lon}
            break
    sender = _parse_user(data.get("sender"))
    recipient = _parse_user(data.get("recipient")) if data.get("recipient") else None
    return MaxMessage(
        id=message_id,
        text=text,
        location=location,
        contact=contact,
        attachments=attachments if attachments else None,
        sender=sender,
        recipient=recipient,
        bot=api,
    )


def _extract_callback_payload(update: dict[str, Any]) -> str | None:
    for key in ("payload", "data", "callback_data"):
        if key in update:
            return update.get(key)
    callback = update.get("callback") or {}
    if "payload" in callback:
        return callback.get("payload")
    message = update.get("message") or {}
    if "payload" in message:
        return message.get("payload")
    body = message.get("body") or {}
    return body.get("payload")


def parse_update(raw_update: dict[str, Any], api: MaxApi) -> MaxUpdate | None:
    update_type = raw_update.get("update_type")
    message_data = raw_update.get("message")

    if update_type == "bot_started":
        user_data = raw_update.get("user") or raw_update.get("sender")
        sender = _parse_user(user_data)
        recipient_data = raw_update.get("recipient") or raw_update.get("bot")
        recipient = _parse_user(recipient_data) if recipient_data else None
        message_id = raw_update.get("id") or raw_update.get("message_id") or raw_update.get("event_id") or "bot_started"
        message = MaxMessage(
            id=message_id,
            text="/start",
            location=None,
            contact=None,
            attachments=None,
            sender=sender,
            recipient=recipient,
            bot=api,
        )
        return MaxUpdate(message=message)

    if update_type in {"message_created", "message_edited"}:
        logger.info("RAW MAX message_data: %s", message_data)
        message = _parse_message(message_data, api)
        if not message:
            return None
        body = message_data.get("body") or {}
        raw_attachments = body.get("attachments") or message_data.get("attachments")
        if raw_attachments and not message.location and not message.contact:
            logger.info("MAX message without parsed attachments: %s", message_data)
        return MaxUpdate(message=message)

    if update_type == "message_callback":
        message = _parse_message(message_data, api)
        payload = _extract_callback_payload(raw_update)
        user_data = raw_update.get("user") or raw_update.get("sender")
        if user_data:
            from_user = _parse_user(user_data)
        elif message and message.recipient and not message.recipient.is_bot:
            from_user = message.recipient
        else:
            from_user = message.sender if message else MaxChat(id=0)
        if not payload:
            logger.warning("Missing callback payload: %s", raw_update)
            return None
        if not message:
            return None
        callback = MaxCallbackQuery(data=str(payload), message=message, from_user=from_user, bot=api)
        return MaxUpdate(callback_query=callback)

    return None
