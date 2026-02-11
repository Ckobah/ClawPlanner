from __future__ import annotations

import datetime

import pytest
from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup

from database.db_controller import db_controller
from entities import Event, TgUser
from handlers.cal import handle_calendar_callback, show_calendar
from handlers.contacts import handle_contact, handle_team_callback
from handlers.events import handle_create_event_callback, handle_delete_event_callback, show_upcoming_events
from handlers.start import start
from tests.fakes import DummyMessage, make_update_with_callback, make_update_with_message


@pytest.mark.asyncio
async def test_start_creates_user_and_replies(db_session_fixture):
    update = make_update_with_message()
    data: dict = {}
    context = type("DummyContext", (), {"user_data": data, "chat_data": data})()

    await start(update, context)

    assert update.message.replies
    reply = update.message.replies[0]
    assert isinstance(reply["reply_markup"], ReplyKeyboardMarkup)


@pytest.mark.asyncio
async def test_handle_contact_creates_relation(db_session_fixture):
    current_user = TgUser.model_validate(type("U", (), {"id": 1, "first_name": "Alice"})())
    await db_controller.save_update_user(tg_user=current_user)

    message = DummyMessage()
    contact = type("Contact", (), {"user_id": 2, "first_name": "Bob", "last_name": None})()
    update = make_update_with_message(message=message, user_id=1, first_name="Alice")
    update.message.contact = contact

    data: dict = {}
    context = type("DummyContext", (), {"user_data": data, "chat_data": data})()
    await handle_contact(update, context=context)

    assert message.replies


@pytest.mark.asyncio
async def test_show_calendar_returns_markup(db_session_fixture):
    update = make_update_with_message()
    data: dict = {}
    context = type("DummyContext", (), {"user_data": data, "chat_data": data})()
    await show_calendar(update, context=context)

    assert update.message.replies
    reply = update.message.replies[0]
    assert isinstance(reply["reply_markup"], InlineKeyboardMarkup)


@pytest.mark.asyncio
async def test_calendar_select_lists_events(db_session_fixture):
    event_date = datetime.date.today()
    event = Event(event_date=event_date, description="Test event", start_time=datetime.time(12, 0), tg_id=1)
    await db_controller.save_event(event)

    update = make_update_with_callback(
        data=f"cal_select_{event_date.year}_{event_date.month}_{event_date.day}",
        user_id=1,
    )

    data: dict = {}
    context = type("DummyContext", (), {"user_data": data, "chat_data": data})()
    await handle_calendar_callback(update, context=context)

    assert update.callback_query.edits
    edit = update.callback_query.edits[0]
    assert isinstance(edit["reply_markup"], InlineKeyboardMarkup)


@pytest.mark.asyncio
async def test_create_event_flow_and_save(db_session_fixture, context):
    event_date = datetime.date.today()

    update = make_update_with_callback(
        data=f"create_event_begin_{event_date.year}_{event_date.month}_{event_date.day}",
        user_id=1,
    )
    await handle_create_event_callback(update, context)
    assert context.user_data.get("event") is not None

    update = make_update_with_callback(
        data=f"create_event_start_{event_date.year}_{event_date.month}_{event_date.day}",
        user_id=1,
    )
    update.callback_query.message = DummyMessage()
    await handle_create_event_callback(update, context)

    event = context.user_data["event"]
    assert event.start_time is not None

    update = make_update_with_callback(
        data=f"create_event_description_{event_date.year}_{event_date.month}_{event_date.day}",
        user_id=1,
    )
    update.callback_query.message = DummyMessage()
    await handle_create_event_callback(update, context)
    assert isinstance(context.user_data.get("await_event_description"), dict)

    text_update = make_update_with_message(message=DummyMessage(text="Desc"), user_id=1)
    from main import handle_text

    await handle_text(text_update, context)
    assert context.user_data.get("await_event_description") is None
    assert context.user_data["event"].description == "Desc"

    update = make_update_with_callback(data="create_event_save_to_db", user_id=1)
    update.callback_query.message = DummyMessage()
    await handle_create_event_callback(update, context)

    assert "event" not in context.user_data


@pytest.mark.asyncio
async def test_delete_event_by_id(db_session_fixture):
    event_date = datetime.date.today()
    event = Event(event_date=event_date, description="Delete me", start_time=datetime.time(13, 0), tg_id=1)
    event_id = await db_controller.save_event(event)

    update = make_update_with_callback(
        data=f"delete_event_id_{event_id}_{event_date.year}_{event_date.month}_{event_date.day}",
        user_id=1,
    )
    update.callback_query.message = DummyMessage()

    data: dict = {}
    context = type("DummyContext", (), {"user_data": data, "chat_data": data})()
    await handle_delete_event_callback(update, context=context)

    assert update.callback_query.edits


@pytest.mark.asyncio
async def test_show_upcoming_events(db_session_fixture):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3)))
    event_date = now.date()
    start_time = (now + datetime.timedelta(hours=1)).time().replace(second=0, microsecond=0)
    event = Event(event_date=event_date, description="Soon", start_time=start_time, tg_id=1)
    await db_controller.save_event(event)

    update = make_update_with_message(user_id=1)
    data: dict = {}
    context = type("DummyContext", (), {"user_data": data, "chat_data": data})()
    await show_upcoming_events(update, context=context)

    assert update.message.replies


@pytest.mark.asyncio
async def test_team_toggle_with_string_participant_id_marks_selected():
    update = make_update_with_callback(data="team_toggle_2", user_id=1)
    data: dict = {"team_participants": {"2": "Bob"}, "team_selected": []}
    context = type("DummyContext", (), {"user_data": data, "chat_data": data})()

    await handle_team_callback(update, context)

    assert set(context.chat_data.get("team_selected", [])) == {2}
    assert update.callback_query.markup_edits
    markup = update.callback_query.markup_edits[0]["reply_markup"]
    button_texts = [button.text for row in markup.inline_keyboard for button in row]
    assert "Bob ❌" in button_texts
