import argparse
import asyncio
import datetime
import logging

import telegram
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import TOKEN, database_url
from database.db_controller import db_controller
from i18n import resolve_user_locale, tr
from max_bot.client import build_max_api
from max_bot.compat import InlineKeyboardButton as MaxInlineKeyboardButton
from max_bot.compat import InlineKeyboardMarkup as MaxInlineKeyboardMarkup

engine = create_async_engine(database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


logger = logging.getLogger(__name__)


def _build_reminder_text(event: dict, send_now: bool, locale: str | None = None) -> str:
    text = tr("Напоминание о событии", locale)
    if not send_now:
        text += f"\n{tr('Через 1 час:', locale)}"
    start_time = event.get("start_time")
    start_str = start_time.strftime("%H:%M") if start_time else ""
    description = event.get("description") or ""
    text += f"\n{tr('Время: {start}', locale).format(start=start_str)}\n{tr('Описание: {description}', locale).format(description=description)}"
    return text


async def send_messages(send_now: bool = False):
    bot = telegram.Bot(token=TOKEN)
    max_api = await build_max_api()
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        now = now.replace(second=0, microsecond=0)
        if not send_now:
            now += datetime.timedelta(hours=1)
        limit = 400
        offset = 0
        while True:
            async with AsyncSessionLocal() as session:
                events_tg = await db_controller.get_current_day_events_all_users(event_dt=now, session=session, limit=limit, offset=offset)
                events_max = await db_controller.get_current_day_events_all_users(
                    event_dt=now, session=session, limit=limit, offset=offset, platform="max"
                )

            logger.info(f"** len events tg: {len(events_tg)}")
            logger.info(f"** len events max: {len(events_max)}")
            if not events_tg and not events_max:
                await engine.dispose()
                break

            for event in events_tg:
                chat_id = event.get("tg_id")
                if not chat_id:
                    continue
                locale = await resolve_user_locale(chat_id, platform="tg")
                text = _build_reminder_text(event, send_now, locale=locale)

                event_id = event.get("event_id")
                reply_markup = None
                if event_id:
                    buttons = [
                        [
                            InlineKeyboardButton(
                                tr("Перенести на 1 час", locale),
                                callback_data=f"reschedule_event_{event_id}_hour",
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                tr("Перенести на завтра", locale),
                                callback_data=f"reschedule_event_{event_id}_day",
                            )
                        ],
                    ]
                    reply_markup = InlineKeyboardMarkup(buttons)

                await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
                await asyncio.sleep(0.001)

            for event in events_max:
                user_id = event.get("tg_id")
                if not user_id:
                    continue
                locale = await resolve_user_locale(user_id, platform="max")
                text = _build_reminder_text(event, send_now, locale=locale)
                event_id = event.get("event_id")
                attachments = None
                if event_id:
                    buttons = [
                        [
                            MaxInlineKeyboardButton(
                                tr("Перенести на 1 час", locale),
                                callback_data=f"reschedule_event_{event_id}_hour",
                            )
                        ],
                        [
                            MaxInlineKeyboardButton(
                                tr("Перенести на завтра", locale),
                                callback_data=f"reschedule_event_{event_id}_day",
                            )
                        ],
                    ]
                    reply_markup = MaxInlineKeyboardMarkup(buttons)
                    attachments = reply_markup.to_attachments()
                await max_api.send_message(text=text, user_id=user_id, attachments=attachments, include_menu=False, locale=locale)
                await asyncio.sleep(0.001)

            await engine.dispose()
            offset += limit
    finally:
        await max_api.close()


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S%z", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description="Choose datetime")
    parser.add_argument("--now", type=bool, help="send events NOW", default=False)

    args = parser.parse_args()

    logger.info(f"Args: {args.now}")

    asyncio.run(send_messages(send_now=args.now))
