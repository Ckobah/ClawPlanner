import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.db_controller import db_controller
from entities import TgUser

logger = logging.getLogger(__name__)


async def handle_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    logger.info("handle_link_callback data=%s chat_id=%s", data, getattr(update.effective_chat, "id", None))
    parts = data.split("_")
    if len(parts) < 5:
        await query.edit_message_text("Некорректный запрос.")
        return

    action = parts[2]
    try:
        tg_id = int(parts[3])
        max_id = int(parts[4])
    except ValueError:
        await query.edit_message_text("Некорректные данные.")
        return

    if not update.effective_chat or update.effective_chat.id != tg_id:
        await query.edit_message_text("Этот запрос не для вас.")
        return

    if action == "decline":
        await query.edit_message_text("Запрос отклонен.")
        return

    if action != "confirm":
        await query.edit_message_text("Неизвестное действие.")
        return

    tg_user = TgUser.model_validate(update.effective_chat)
    await db_controller.save_update_user(tg_user=tg_user)

    ok, message = await db_controller.link_tg_max(tg_id=tg_id, max_id=max_id)
    logger.info("link_tg_max result ok=%s message=%s tg_id=%s max_id=%s", ok, message, tg_id, max_id)
    await query.edit_message_text(message)
