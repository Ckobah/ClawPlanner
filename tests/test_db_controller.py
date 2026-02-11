from __future__ import annotations

import datetime
from datetime import timedelta, timezone

import pytest

from config import DEFAULT_TIMEZONE
from database.db_controller import db_controller
from database.models.user_model import UserRelation
from database import session as db_session
from entities import Event, Recurrent, TgUser


@pytest.mark.asyncio
async def test_get_current_day_events_by_user_returns_string(db_session_fixture):
    event_date = datetime.date.today()
    event = Event(event_date=event_date, description="Daily", start_time=datetime.time(9, 0), tg_id=1, recurrent=Recurrent.never)
    await db_controller.save_event(event)

    events = await db_controller.get_current_day_events_by_user(
        user_id=1,
        year=event_date.year,
        month=event_date.month,
        day=event_date.day,
    )

    assert isinstance(events, str)
    assert "Daily" in events


def test_get_effective_month_day():
    assert db_controller.get_effective_month_day(2025, 2, 30) == 28


def test_get_weekday_days_in_month():
    # January 2024 Mondays are 1, 8, 15, 22, 29
    assert db_controller.get_weekday_days_in_month(2024, 1, 0) == [1, 8, 15, 22, 29]


@pytest.mark.asyncio
async def test_get_current_month_events_by_user_single_event(db_session_fixture):
    event_date = datetime.date(2025, 3, 10)
    event = Event(event_date=event_date, description="Single", start_time=datetime.time(9, 0), tg_id=1, recurrent=Recurrent.never)
    await db_controller.save_event(event)

    event_dict = await db_controller.get_current_month_events_by_user(user_id=1, month=event_date.month, year=event_date.year)

    assert event_dict[event_date.day] == 1


@pytest.mark.asyncio
async def test_get_current_month_events_by_user_daily_cancel(db_session_fixture):
    event_date = datetime.date(2025, 3, 1)
    cancel_date = datetime.date(2025, 3, 2)
    event = Event(event_date=event_date, description="Daily", start_time=datetime.time(8, 0), tg_id=1, recurrent=Recurrent.daily)
    event_id = await db_controller.save_event(event)
    await db_controller.create_cancel_event(event_id=event_id, cancel_date=cancel_date)

    event_dict = await db_controller.get_current_month_events_by_user(user_id=1, month=event_date.month, year=event_date.year)

    assert event_dict[cancel_date.day] == 0


@pytest.mark.asyncio
async def test_create_cancel_event_excludes_day(db_session_fixture):
    event_date = datetime.date.today()
    event = Event(event_date=event_date, description="Repeat", start_time=datetime.time(10, 0), tg_id=1, recurrent=Recurrent.daily)
    event_id = await db_controller.save_event(event)

    await db_controller.create_cancel_event(event_id=event_id, cancel_date=event_date)

    events = await db_controller.get_current_day_events_by_user(
        user_id=1,
        year=event_date.year,
        month=event_date.month,
        day=event_date.day,
    )

    assert events == ""


@pytest.mark.asyncio
async def test_get_current_day_events_by_user_deleted_returns_list(db_session_fixture):
    event_date = datetime.date.today()
    event = Event(event_date=event_date, description="To delete", start_time=datetime.time(11, 0), tg_id=1, recurrent=Recurrent.never)
    await db_controller.save_event(event)

    events = await db_controller.get_current_day_events_by_user(
        user_id=1,
        year=event_date.year,
        month=event_date.month,
        day=event_date.day,
        deleted=True,
    )

    assert isinstance(events, list)
    assert events and isinstance(events[0], tuple)


@pytest.mark.asyncio
async def test_delete_event_by_id_returns_tuple(db_session_fixture):
    event_date = datetime.date.today()
    event = Event(event_date=event_date, description="Remove me", start_time=datetime.time(12, 0), tg_id=1, recurrent=Recurrent.never)
    event_id = await db_controller.save_event(event)

    single_event, message = await db_controller.delete_event_by_id(event_id=event_id)

    assert single_event is True
    assert "Remove me" in message


@pytest.mark.asyncio
async def test_get_nearest_events_contains_single_event(db_session_fixture):
    user_tz = timezone(timedelta(hours=DEFAULT_TIMEZONE))
    now = datetime.datetime.now(user_tz)
    event_date = now.date()
    start_time = (now + timedelta(hours=1)).time().replace(second=0, microsecond=0)
    event = Event(event_date=event_date, description="Soon", start_time=start_time, tg_id=1, recurrent=Recurrent.never)
    await db_controller.save_event(event)

    events = await db_controller.get_nearest_events(user_id=1)

    assert any("Soon" in list(item.values())[0][0] for item in events)


@pytest.mark.asyncio
async def test_get_current_day_events_all_users(db_session_fixture):
    user_tz = timezone(timedelta(hours=DEFAULT_TIMEZONE))
    event_date = datetime.date.today()
    start_time = datetime.time(14, 0)
    event = Event(event_date=event_date, description="All users", start_time=start_time, tg_id=42, recurrent=Recurrent.never)
    await db_controller.save_event(event)

    event_dt = datetime.datetime.combine(event_date, start_time).replace(tzinfo=user_tz).astimezone(timezone.utc)
    event_dt = event_dt.replace(tzinfo=None)

    async with db_session.AsyncSessionLocal() as session:
        events = await db_controller.get_current_day_events_all_users(event_dt=event_dt, session=session)

    assert events
    assert events[0]["tg_id"] == 42


@pytest.mark.asyncio
async def test_resave_event_to_participant_missing_event_returns_none(db_session_fixture):
    result = await db_controller.resave_event_to_participant(event_id=999999, user_id=2)
    assert result is None


@pytest.mark.asyncio
async def test_save_update_user_creates_relation(db_session_fixture):
    current = TgUser.model_validate(type("U", (), {"id": 1, "first_name": "Alice"})())
    await db_controller.save_update_user(tg_user=current)

    contact = TgUser.model_validate(type("U", (), {"id": 2, "first_name": "Bob"})())
    await db_controller.save_update_user(tg_user=contact, from_contact=True, current_user=1)

    async with db_session.AsyncSessionLocal() as session:
        result = (await session.execute(UserRelation.__table__.select())).all()

    assert result
