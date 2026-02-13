import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

import config
from config import NEAREST_EVENTS_DAYS
from database.models.event_models import CanceledEvent, DbEvent, EventParticipant
from database.models.note_model import DbNote
from database.models.user_model import User as DB_User
from database.models.user_model import UserRelation
from database.session import AsyncSessionLocal
from entities import Event, MaxUser, Recurrent, TgUser

logger = logging.getLogger(__name__)


class DBController:
    @staticmethod
    def _normalize_platform(platform: str | None) -> str:
        return "max" if platform == "max" else "tg"

    @classmethod
    def _user_id_column(cls, platform: str | None):
        platform = cls._normalize_platform(platform)
        return DB_User.max_id if platform == "max" else DB_User.tg_id

    @classmethod
    def _event_user_column(cls, platform: str | None):
        return DbEvent.user_id

    @classmethod
    def _participant_id_column(cls, platform: str | None):
        return EventParticipant.participant_user_id

    @classmethod
    async def _resolve_user_row_id_by_external(
        cls,
        external_id: int | None,
        platform: str | None,
        session: AsyncSession,
    ) -> int | None:
        if external_id is None:
            return None
        user_col = cls._user_id_column(platform)
        return (await session.execute(select(DB_User.id).where(user_col == int(external_id)))).scalar_one_or_none()

    @classmethod
    async def _resolve_external_ids_by_user_row(
        cls,
        user_ids: list[int],
        platform: str | None,
        session: AsyncSession,
    ) -> dict[int, int]:
        user_ids = [int(item) for item in user_ids if item is not None]
        if not user_ids:
            return {}
        user_col = cls._user_id_column(platform)
        rows = (
            await session.execute(
                select(DB_User.id, user_col).where(DB_User.id.in_(user_ids), user_col.is_not(None))
            )
        ).all()
        return {int(row[0]): int(row[1]) for row in rows if row[1] is not None}
    @staticmethod
    def get_effective_month_day(year: int, month: int, day: int) -> int:
        _, num_days = monthrange(year, month)
        return day if day <= num_days else num_days

    @staticmethod
    async def save_update_user(tg_user: TgUser, from_contact: bool = False, current_user: int | None = None) -> None | TgUser:
        logger.info(f"db_controller save: {tg_user}")
        async with AsyncSessionLocal() as session:
            query = select(DB_User).where(DB_User.tg_id == tg_user.tg_id)
            result = (await session.execute(query)).scalar_one_or_none()

            if not result:
                tg_user_dict = tg_user.model_dump(exclude={"title"}, exclude_defaults=True, exclude_unset=True)
                user = DB_User(**tg_user_dict)
                user.is_active = False if from_contact else True
                session.add(user)
            else:
                tg_user_dict = tg_user.model_dump(exclude={"title"}, exclude_defaults=True, exclude_unset=True)
                if tg_user_dict.get("language_code") is None:
                    tg_user_dict.pop("language_code", None)
                if from_contact:
                    tg_user_dict.pop("is_active", None)
                else:
                    tg_user_dict["is_active"] = True
                update_query = update(DB_User).where(DB_User.tg_id == tg_user.tg_id).values(**tg_user_dict).returning(DB_User)
                user = (await session.execute(update_query)).scalar_one_or_none()

            await session.commit()
            await session.refresh(user)

            if from_contact and current_user:
                current_user_query = select(DB_User).where(DB_User.tg_id == current_user)
                current_user = (await session.execute(current_user_query)).scalar_one_or_none()

                new_user_relation = UserRelation(
                    user_id=current_user.id,
                    related_user_id=user.id,
                )
                session.add(new_user_relation)

                try:
                    await session.commit()
                except IntegrityError:
                    return None

        user.id = user.tg_id
        user.time_zone = config.DEFAULT_TIMEZONE_NAME if not user.time_zone else user.time_zone
        return TgUser.model_validate(user)

    @staticmethod
    async def save_update_max_user(max_user: MaxUser, from_contact: bool = False, current_user: int | None = None) -> None | MaxUser:
        logger.info(f"db_controller save max: {max_user}")
        async with AsyncSessionLocal() as session:
            query = select(DB_User).where(DB_User.max_id == max_user.max_id)
            result = (await session.execute(query)).scalar_one_or_none()

            if not result:
                max_user_dict = max_user.model_dump(exclude={"title"}, exclude_defaults=True, exclude_unset=True)
                user = DB_User(**max_user_dict)
                user.is_active = False if from_contact else True
                session.add(user)
            else:
                max_user_dict = max_user.model_dump(exclude={"title"}, exclude_defaults=True, exclude_unset=True)
                if max_user_dict.get("language_code") is None:
                    max_user_dict.pop("language_code", None)
                if from_contact:
                    max_user_dict.pop("is_active", None)
                else:
                    max_user_dict["is_active"] = True
                update_query = update(DB_User).where(DB_User.max_id == max_user.max_id).values(**max_user_dict).returning(DB_User)
                user = (await session.execute(update_query)).scalar_one_or_none()

            await session.commit()
            await session.refresh(user)

            if from_contact and current_user:
                current_user_query = select(DB_User).where(DB_User.max_id == current_user)
                current_user = (await session.execute(current_user_query)).scalar_one_or_none()

                new_user_relation = UserRelation(
                    user_id=current_user.id,
                    related_user_id=user.id,
                )
                session.add(new_user_relation)

                try:
                    await session.commit()
                except IntegrityError:
                    return None

        user.id = user.max_id
        user.time_zone = config.DEFAULT_TIMEZONE_NAME if not user.time_zone else user.time_zone
        return MaxUser.model_validate(user)

    @staticmethod
    async def get_user(tg_id: int, platform: str | None = None) -> TgUser | MaxUser | None:
        user_col = DBController._user_id_column(platform)
        user_attr = user_col.key
        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(DB_User).where(user_col == tg_id))).scalar_one_or_none()
            if not user:
                return None

            user.id = getattr(user, user_attr)
            user.time_zone = config.DEFAULT_TIMEZONE_NAME if not user.time_zone else user.time_zone
            if platform == "max":
                return MaxUser.model_validate(user)
            return TgUser.model_validate(user)

    @staticmethod
    async def get_user_row_id(external_id: int, platform: str | None = None) -> int | None:
        user_col = DBController._user_id_column(platform)
        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(DB_User.id).where(user_col == external_id))).scalar_one_or_none()
            return int(user) if user is not None else None

    @staticmethod
    async def set_user_language(user_id: int, language_code: str, platform: str | None = None) -> None:
        user_col = DBController._user_id_column(platform)
        async with AsyncSessionLocal() as session:
            existing_user = (await session.execute(select(DB_User).where(user_col == user_id))).scalar_one_or_none()
            if existing_user:
                await session.execute(update(DB_User).where(user_col == user_id).values(language_code=language_code))
            else:
                user_kwargs = {user_col.key: user_id, "language_code": language_code}
                session.add(DB_User(**user_kwargs))
            await session.commit()

    @staticmethod
    async def get_max_user(max_id: int) -> MaxUser | None:
        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(DB_User).where(DB_User.max_id == max_id))).scalar_one_or_none()
            if not user:
                return None

            user.id = user.max_id
            user.time_zone = config.DEFAULT_TIMEZONE_NAME if not user.time_zone else user.time_zone
            return MaxUser.model_validate(user)

    @staticmethod
    async def get_linked_tg_id(max_id: int) -> int | None:
        async with AsyncSessionLocal() as session:
            user = (await session.execute(select(DB_User).where(DB_User.max_id == max_id))).scalar_one_or_none()
            if not user:
                return None
            return user.tg_id

    @staticmethod
    async def link_tg_max(tg_id: int, max_id: int) -> tuple[bool, str]:
        async with AsyncSessionLocal() as session:
            tg_user = (await session.execute(select(DB_User).where(DB_User.tg_id == tg_id))).scalar_one_or_none()
            max_user = (await session.execute(select(DB_User).where(DB_User.max_id == max_id))).scalar_one_or_none()

            if tg_user and tg_user.max_id and tg_user.max_id != max_id:
                return False, "Этот Telegram ID уже связан с другим MAX ID."
            if max_user and max_user.tg_id and max_user.tg_id != tg_id:
                return False, "Этот MAX ID уже связан с другим Telegram ID."
            if tg_user and max_user and tg_user.id != max_user.id:
                primary = tg_user
                secondary = max_user

                # Avoid unique constraint conflicts while merging.
                await session.execute(
                    update(DB_User)
                    .where(DB_User.id == secondary.id)
                    .values(tg_id=None, max_id=None)
                )

                merged_values: dict = {
                    "tg_id": tg_id,
                    "max_id": max_id,
                }
                for attr in (
                    "username",
                    "first_name",
                    "last_name",
                    "time_shift",
                    "time_zone",
                    "language_code",
                    "is_active",
                    "is_chat",
                ):
                    if getattr(primary, attr) is None and getattr(secondary, attr) is not None:
                        merged_values[attr] = getattr(secondary, attr)

                await session.execute(update(DB_User).where(DB_User.id == primary.id).values(**merged_values))

                await session.execute(
                    delete(UserRelation).where(
                        UserRelation.user_id == secondary.id,
                        UserRelation.related_user_id.in_(
                            select(UserRelation.related_user_id).where(UserRelation.user_id == primary.id)
                        ),
                    )
                )
                await session.execute(
                    delete(UserRelation).where(
                        UserRelation.related_user_id == secondary.id,
                        UserRelation.user_id.in_(
                            select(UserRelation.user_id).where(UserRelation.related_user_id == primary.id)
                        ),
                    )
                )
                await session.execute(update(UserRelation).where(UserRelation.user_id == secondary.id).values(user_id=primary.id))
                await session.execute(
                    update(UserRelation).where(UserRelation.related_user_id == secondary.id).values(related_user_id=primary.id)
                )
                await session.execute(
                    update(DbNote).where(DbNote.user_id == secondary.id).values(user_id=primary.id)
                )
                await session.execute(update(DbEvent).where(DbEvent.user_id == secondary.id).values(user_id=primary.id))
                await session.execute(
                    update(DbEvent).where(DbEvent.creator_user_id == secondary.id).values(creator_user_id=primary.id)
                )
                await session.execute(
                    update(EventParticipant)
                    .where(EventParticipant.participant_user_id == secondary.id)
                    .values(participant_user_id=primary.id)
                )

                await session.execute(delete(DB_User).where(DB_User.id == secondary.id))
                await session.commit()

                tg_user = primary
                max_user = primary


            if tg_user:
                await session.execute(update(DB_User).where(DB_User.tg_id == tg_id).values(max_id=max_id))
            elif max_user:
                await session.execute(update(DB_User).where(DB_User.max_id == max_id).values(tg_id=tg_id))
            else:
                session.add(DB_User(tg_id=tg_id, max_id=max_id))

            await session.commit()

            await session.execute(
                update(DbEvent)
                .where(DbEvent.tg_id == tg_id, DbEvent.max_id.is_(None))
                .values(max_id=max_id)
            )
            await session.execute(
                update(DbEvent)
                .where(DbEvent.max_id == max_id, DbEvent.tg_id.is_(None))
                .values(tg_id=tg_id)
            )
            await session.execute(
                update(DbEvent)
                .where(DbEvent.creator_tg_id == tg_id, DbEvent.creator_max_id.is_(None))
                .values(creator_max_id=max_id)
            )
            await session.execute(
                update(DbEvent)
                .where(DbEvent.creator_max_id == max_id, DbEvent.creator_tg_id.is_(None))
                .values(creator_tg_id=tg_id)
            )
            await session.execute(
                update(EventParticipant)
                .where(EventParticipant.participant_tg_id == tg_id, EventParticipant.participant_max_id.is_(None))
                .values(participant_max_id=max_id)
            )
            await session.execute(
                update(EventParticipant)
                .where(EventParticipant.participant_max_id == max_id, EventParticipant.participant_tg_id.is_(None))
                .values(participant_tg_id=tg_id)
            )
            primary_user = (await session.execute(select(DB_User).where(DB_User.tg_id == tg_id))).scalar_one_or_none()
            if primary_user:
                await session.execute(
                    update(DbEvent)
                    .where(DbEvent.user_id.is_(None), or_(DbEvent.tg_id == tg_id, DbEvent.max_id == max_id))
                    .values(user_id=primary_user.id)
                )
                await session.execute(
                    update(DbEvent)
                    .where(DbEvent.creator_user_id.is_(None), or_(DbEvent.creator_tg_id == tg_id, DbEvent.creator_max_id == max_id))
                    .values(creator_user_id=primary_user.id)
                )
                await session.execute(
                    update(EventParticipant)
                    .where(
                        EventParticipant.participant_user_id.is_(None),
                        or_(EventParticipant.participant_tg_id == tg_id, EventParticipant.participant_max_id == max_id),
                    )
                    .values(participant_user_id=primary_user.id)
                )
            await session.commit()

        return True, "Связь подтверждена."

    @staticmethod
    async def get_users_short_names(tg_ids: list[int], platform: str | None = None) -> dict[int, str]:
        if not tg_ids:
            return {}

        user_col = DBController._user_id_column(platform)
        user_attr = user_col.key

        async with AsyncSessionLocal() as session:
            users = (await session.execute(select(DB_User).where(user_col.in_(tg_ids)))).scalars().all()

        names: dict[int, str] = {}
        for user in users:
            if user.first_name:
                name = user.first_name
            elif user.username:
                name = user.username
            else:
                name = str(getattr(user, user_attr))
            names[getattr(user, user_attr)] = name

        return names

    @staticmethod
    async def get_notes(user_id: int) -> list[DbNote]:
        async with AsyncSessionLocal() as session:
            query = select(DbNote).where(DbNote.user_id == user_id).order_by(DbNote.updated_at.desc(), DbNote.id.desc())
            return list((await session.execute(query)).scalars().all())

    @staticmethod
    async def get_note_by_id(note_id: int, user_id: int) -> DbNote | None:
        async with AsyncSessionLocal() as session:
            query = select(DbNote).where(DbNote.id == int(note_id), DbNote.user_id == user_id)
            return (await session.execute(query)).scalar_one_or_none()

    @staticmethod
    async def create_note(user_id: int, note_text: str) -> DbNote:
        note = DbNote(user_id=user_id, note_text=note_text)
        async with AsyncSessionLocal() as session:
            session.add(note)
            await session.commit()
            await session.refresh(note)
        return note

    @staticmethod
    async def update_note(note_id: int, user_id: int, note_text: str) -> DbNote | None:
        async with AsyncSessionLocal() as session:
            query = (
                update(DbNote)
                .where(DbNote.id == int(note_id), DbNote.user_id == user_id)
                .values(note_text=note_text, updated_at=func.now())
                .returning(DbNote)
            )
            note = (await session.execute(query)).scalar_one_or_none()
            await session.commit()
            return note

    @staticmethod
    async def delete_note(note_id: int, user_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            query = delete(DbNote).where(DbNote.id == int(note_id), DbNote.user_id == user_id)
            result = await session.execute(query)
            await session.commit()
            return bool(result.rowcount)

    @staticmethod
    async def get_participants(tg_id: int, include_inactive: bool = False, platform: str | None = None) -> dict[int, str] | None:
        async with AsyncSessionLocal() as session:
            db_user_alias = aliased(DB_User)
            user_col = DBController._user_id_column(platform)
            user_attr = user_col.key
            filters = [getattr(db_user_alias, user_attr) == tg_id]
            if not include_inactive:
                filters.append(DB_User.is_active.is_(True))
            query = (
                select(DB_User)
                .join(UserRelation, DB_User.id == UserRelation.related_user_id)
                .join(db_user_alias, UserRelation.user_id == db_user_alias.id)
                .where(*filters)
            )

            participants = (await session.execute(query)).scalars().all()

            return {getattr(item, user_attr): item.first_name for item in participants}

    @staticmethod
    async def get_participants_with_status(
        tg_id: int,
        include_inactive: bool = True,
        platform: str | None = None,
    ) -> dict[int, tuple[str, bool]]:
        async with AsyncSessionLocal() as session:
            db_user_alias = aliased(DB_User)
            user_col = DBController._user_id_column(platform)
            user_attr = user_col.key
            filters = [getattr(db_user_alias, user_attr) == tg_id]
            if not include_inactive:
                filters.append(DB_User.is_active.is_(True))
            query = (
                select(DB_User)
                .join(UserRelation, DB_User.id == UserRelation.related_user_id)
                .join(db_user_alias, UserRelation.user_id == db_user_alias.id)
                .where(*filters)
            )

            participants = (await session.execute(query)).scalars().all()

            return {getattr(item, user_attr): (item.first_name, bool(item.is_active)) for item in participants}

    @staticmethod
    async def get_event_participants(event_id: int, platform: str | None = None) -> list[int]:
        async with AsyncSessionLocal() as session:
            participant_col = DBController._participant_id_column(platform)
            query = select(participant_col).where(EventParticipant.event_id == int(event_id))
            participant_user_ids = [int(item) for item in (await session.execute(query)).scalars().all() if item is not None]
            external_map = await DBController._resolve_external_ids_by_user_row(participant_user_ids, platform, session)
            return [external_map[item] for item in participant_user_ids if item in external_map]

    @staticmethod
    async def set_event_participants(event_id: int, participant_ids: list[int], platform: str | None = None) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(EventParticipant).where(EventParticipant.event_id == int(event_id)))
            if participant_ids:
                user_col = DBController._user_id_column(platform)
                normalized_ids = [int(item) for item in participant_ids]
                existing_users = (
                    await session.execute(select(DB_User).where(user_col.in_(normalized_ids)))
                ).scalars().all()
                row_by_external = {int(getattr(user, user_col.key)): int(user.id) for user in existing_users if getattr(user, user_col.key)}
                missing = [item for item in normalized_ids if item not in row_by_external]
                if missing:
                    for external_id in missing:
                        session.add(DB_User(**{user_col.key: int(external_id)}))
                    await session.flush()
                    new_users = (
                        await session.execute(select(DB_User).where(user_col.in_(missing)))
                    ).scalars().all()
                    for user in new_users:
                        ext = getattr(user, user_col.key)
                        if ext is not None:
                            row_by_external[int(ext)] = int(user.id)
                session.add_all(
                    [
                        EventParticipant(
                            event_id=int(event_id),
                            participant_user_id=row_by_external[int(participant_id)],
                            participant_tg_id=int(participant_id) if platform != "max" else None,
                            participant_max_id=int(participant_id) if platform == "max" else None,
                        )
                        for participant_id in participant_ids
                        if int(participant_id) in row_by_external
                    ]
                )
            await session.commit()

    @staticmethod
    async def delete_participants(current_tg_id: int, related_tg_ids: list[int], platform: str | None = None) -> int:
        if not related_tg_ids:
            return 0

        async with AsyncSessionLocal() as session:
            user_col = DBController._user_id_column(platform)
            current_user = (await session.execute(select(DB_User).where(user_col == current_tg_id))).scalar_one_or_none()
            if not current_user:
                return 0

            related_users = (await session.execute(select(DB_User).where(user_col.in_(related_tg_ids)))).scalars().all()
            if not related_users:
                return 0

            related_ids = [user.id for user in related_users]
            delete_query = delete(UserRelation).where(
                UserRelation.user_id == current_user.id,
                UserRelation.related_user_id.in_(related_ids),
            )
            result = await session.execute(delete_query)
            await session.commit()

            return result.rowcount or 0

    @staticmethod
    async def save_event(event: Event, tz_name: str = config.DEFAULT_TIMEZONE_NAME) -> int | None:
        logger.info(f"db_controller save event: {event}")

        user_tz = ZoneInfo(tz_name)

        start_datetime_tz = datetime.combine(event.event_date, event.start_time).replace(tzinfo=user_tz).astimezone(timezone.utc)

        stop_datetime_tz = None
        if event.stop_time:
            stop_datetime_tz = datetime.combine(event.event_date, event.stop_time).replace(tzinfo=user_tz).astimezone(timezone.utc)

        async with AsyncSessionLocal() as session:
            owner_user: DB_User | None = None
            creator_user: DB_User | None = None

            if event.max_id and (event.tg_id is None or event.creator_tg_id is None):
                user = (await session.execute(select(DB_User).where(DB_User.max_id == event.max_id))).scalar_one_or_none()
                if user and user.tg_id:
                    if event.tg_id is None:
                        event.tg_id = user.tg_id
                    if event.creator_tg_id is None:
                        event.creator_tg_id = user.tg_id
                owner_user = user or owner_user
            if event.tg_id and (event.max_id is None or event.creator_max_id is None):
                user = (await session.execute(select(DB_User).where(DB_User.tg_id == event.tg_id))).scalar_one_or_none()
                if user and user.max_id:
                    if event.max_id is None:
                        event.max_id = user.max_id
                    if event.creator_max_id is None:
                        event.creator_max_id = user.max_id
                owner_user = user or owner_user

            if owner_user is None and event.tg_id is not None:
                owner_user = (await session.execute(select(DB_User).where(DB_User.tg_id == event.tg_id))).scalar_one_or_none()
            if owner_user is None and event.max_id is not None:
                owner_user = (await session.execute(select(DB_User).where(DB_User.max_id == event.max_id))).scalar_one_or_none()

            if owner_user is None:
                owner_kwargs: dict = {}
                if event.tg_id is not None:
                    owner_kwargs["tg_id"] = int(event.tg_id)
                if event.max_id is not None:
                    owner_kwargs["max_id"] = int(event.max_id)
                if owner_kwargs:
                    owner_user = DB_User(**owner_kwargs)
                    session.add(owner_user)
                    await session.flush()

            if event.creator_tg_id is not None:
                creator_user = (
                    await session.execute(select(DB_User).where(DB_User.tg_id == int(event.creator_tg_id)))
                ).scalar_one_or_none()
            if creator_user is None and event.creator_max_id is not None:
                creator_user = (
                    await session.execute(select(DB_User).where(DB_User.max_id == int(event.creator_max_id)))
                ).scalar_one_or_none()
            if creator_user is None:
                creator_user = owner_user

            creator_tg_id = event.creator_tg_id if event.creator_tg_id is not None else event.tg_id
            creator_max_id = event.creator_max_id if event.creator_max_id is not None else event.max_id
            new_event = DbEvent(
                description=event.description,
                emoji=event.emoji,
                start_time=start_datetime_tz.time(),
                single_event=True if event.recurrent == Recurrent.never else False,
                daily=True if event.recurrent == Recurrent.daily else False,
                weekly=start_datetime_tz.weekday() if event.recurrent == Recurrent.weekly else None,
                monthly=start_datetime_tz.day if event.recurrent == Recurrent.monthly else None,
                annual_day=start_datetime_tz.day if event.recurrent == Recurrent.annual else None,
                annual_month=start_datetime_tz.month if event.recurrent == Recurrent.annual else None,
                tg_id=event.tg_id,
                max_id=event.max_id,
                creator_tg_id=creator_tg_id,
                creator_max_id=creator_max_id,
                user_id=owner_user.id if owner_user else None,
                creator_user_id=creator_user.id if creator_user else None,
                start_at=start_datetime_tz,
                stop_at=stop_datetime_tz,
            )
            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)

            if new_event.max_id and (new_event.tg_id is None or new_event.creator_tg_id is None):
                user = (await session.execute(select(DB_User).where(DB_User.max_id == new_event.max_id))).scalar_one_or_none()
                if user and user.tg_id:
                    await session.execute(
                        update(DbEvent)
                        .where(DbEvent.id == new_event.id)
                        .values(
                            tg_id=new_event.tg_id or user.tg_id,
                            creator_tg_id=new_event.creator_tg_id or user.tg_id,
                        )
                    )
                    await session.commit()
                    await session.refresh(new_event)
            if new_event.tg_id and (new_event.max_id is None or new_event.creator_max_id is None):
                user = (await session.execute(select(DB_User).where(DB_User.tg_id == new_event.tg_id))).scalar_one_or_none()
                if user and user.max_id:
                    await session.execute(
                        update(DbEvent)
                        .where(DbEvent.id == new_event.id)
                        .values(
                            max_id=new_event.max_id or user.max_id,
                            creator_max_id=new_event.creator_max_id or user.max_id,
                        )
                    )
                    await session.commit()
                    await session.refresh(new_event)

            return new_event.id

    @staticmethod
    async def get_event_by_id(event_id: int, tz_name: str = config.DEFAULT_TIMEZONE_NAME) -> Event | None:
        user_tz = ZoneInfo(tz_name)
        async with AsyncSessionLocal() as session:
            query = select(DbEvent).where(DbEvent.id == int(event_id))
            db_event = (await session.execute(query)).scalar_one_or_none()
            if not db_event:
                return None
            owner_user = None
            creator_user = None
            if db_event.user_id is not None:
                owner_user = (await session.execute(select(DB_User).where(DB_User.id == db_event.user_id))).scalar_one_or_none()
            if db_event.creator_user_id is not None:
                creator_user = (await session.execute(select(DB_User).where(DB_User.id == db_event.creator_user_id))).scalar_one_or_none()

        start_local = db_event.start_at.astimezone(user_tz)
        stop_local_time = db_event.stop_at.astimezone(user_tz).time() if db_event.stop_at else None

        if db_event.daily:
            recurrent = Recurrent.daily
        elif db_event.weekly is not None:
            recurrent = Recurrent.weekly
        elif db_event.monthly is not None:
            recurrent = Recurrent.monthly
        elif db_event.annual_day is not None:
            recurrent = Recurrent.annual
        else:
            recurrent = Recurrent.never

        owner_tg_id = db_event.tg_id or (owner_user.tg_id if owner_user else None)
        owner_max_id = db_event.max_id or (owner_user.max_id if owner_user else None)
        creator_tg_id = db_event.creator_tg_id or (creator_user.tg_id if creator_user else owner_tg_id)
        creator_max_id = db_event.creator_max_id or (creator_user.max_id if creator_user else owner_max_id)

        return Event(
            event_date=start_local.date(),
            description=db_event.description,
            emoji=db_event.emoji,
            start_time=start_local.time(),
            stop_time=stop_local_time,
            recurrent=recurrent,
            tg_id=owner_tg_id,
            creator_tg_id=creator_tg_id,
            max_id=owner_max_id,
            creator_max_id=creator_max_id,
        )

    @staticmethod
    async def update_event(event_id: int, event: Event, tz_name: str = config.DEFAULT_TIMEZONE_NAME) -> int | None:
        user_tz = ZoneInfo(tz_name)
        start_datetime_tz = datetime.combine(event.event_date, event.start_time).replace(tzinfo=user_tz).astimezone(timezone.utc)

        stop_datetime_tz = None
        if event.stop_time:
            stop_datetime_tz = datetime.combine(event.event_date, event.stop_time).replace(tzinfo=user_tz).astimezone(timezone.utc)

        values = dict(
            description=event.description,
            emoji=event.emoji,
            start_time=start_datetime_tz.time(),
            start_at=start_datetime_tz,
            stop_at=stop_datetime_tz,
            single_event=True if event.recurrent == Recurrent.never else False,
            daily=True if event.recurrent == Recurrent.daily else False,
            weekly=start_datetime_tz.weekday() if event.recurrent == Recurrent.weekly else None,
            monthly=start_datetime_tz.day if event.recurrent == Recurrent.monthly else None,
            annual_day=start_datetime_tz.day if event.recurrent == Recurrent.annual else None,
            annual_month=start_datetime_tz.month if event.recurrent == Recurrent.annual else None,
        )

        async with AsyncSessionLocal() as session:
            update_query = update(DbEvent).where(DbEvent.id == int(event_id)).values(**values).returning(DbEvent.id)
            updated_id = (await session.execute(update_query)).scalar_one_or_none()
            await session.commit()
            return updated_id

    @staticmethod
    def get_weekday_days_in_month(year: int, month: int, weekday: int) -> list[int]:
        _, num_days = monthrange(year, month)
        return [day for day in range(1, num_days + 1) if date(year, month, day).weekday() == weekday]

    async def get_current_month_events_by_user(
        self, user_id: int, month: int, year: int, tz_name: str = config.DEFAULT_TIMEZONE_NAME, platform: str | None = None
    ) -> dict[int, int]:
        _, num_days = monthrange(year, month)

        user_tz = ZoneInfo(tz_name)

        month_start_local = datetime(year, month, 1, 0, 0, 0, tzinfo=user_tz)
        month_end_local = datetime(year, month, num_days, 23, 59, 59, tzinfo=user_tz)

        # Переводим границы в UTC
        month_start_utc = month_start_local.astimezone(timezone.utc)
        month_end_utc = month_end_local.astimezone(timezone.utc)

        event_user_col = self._event_user_column(platform)
        async with AsyncSessionLocal() as session:
            user_row_id = await self._resolve_user_row_id_by_external(user_id, platform, session)
            if user_row_id is None:
                empty = {day: 0 for day in range(1, num_days + 1)}
                empty[0] = []
                return empty
            query = select(DbEvent).where(
                event_user_col == user_row_id,
                DbEvent.start_at <= month_end_utc,
                or_(
                    and_(
                        DbEvent.single_event.is_(True),
                        DbEvent.start_at >= month_start_utc,
                    ),
                    and_(
                        or_(
                            DbEvent.daily.is_(True),
                            DbEvent.weekly.is_not(None),
                            DbEvent.monthly.is_not(None),
                            and_(DbEvent.annual_month.is_not(None), DbEvent.annual_month.in_([month_start_utc.month, month_end_utc.month])),
                        ),
                    ),
                ),
            )

            events = (await session.execute(query)).scalars().all()

        event_dict: dict[int, int | list] = {day: 0 for day in range(1, num_days + 1)}
        event_dict[0] = []  # для daily

        def is_canceled(ev: DbEvent, d: date) -> bool:
            return d in {_ev.cancel_date for _ev in ev.canceled_events}

        for event in events:
            # Локальное время начала события
            start_local_dt = event.start_at.astimezone(user_tz)
            end_local_time = event.stop_at.astimezone(user_tz).time() if event.stop_at else None  # noqa

            # SINGLE EVENT
            if event.single_event:
                event_dict[start_local_dt.day] += 1

            # DAILY EVENTS
            elif event.daily:
                event_dict[0].append(event)

            # MONTHLY EVENTS
            elif event.monthly is not None:
                day_in_month = self.get_effective_month_day(year, month, start_local_dt.day)
                calculated_date = date(year, month, day_in_month)
                if calculated_date >= start_local_dt.date() and not is_canceled(event, calculated_date):
                    event_dict[day_in_month] += 1

            # ANNUAL EVENTS
            elif event.annual_day is not None:
                start_local = event.start_at.astimezone(user_tz)

                event_month = start_local.month
                event_day = start_local.day

                if event_month != month:
                    continue

                calculated_date = date(year, month, event_day)

                if calculated_date >= start_local.date() and not is_canceled(event, calculated_date):
                    event_dict[event_day] += 1

            # WEEKLY EVENTS
            elif event.weekly is not None:
                weekday_user_tz = event.start_at.astimezone(user_tz).weekday()
                weekdays = self.get_weekday_days_in_month(year=year, month=month, weekday=weekday_user_tz)
                for day in weekdays:
                    calculated_date_user_tz = date(year, month, day)
                    if calculated_date_user_tz >= start_local_dt.date() and not is_canceled(event, calculated_date_user_tz):
                        event_dict[day] += 1

        for daily_event in event_dict[0]:
            start_day = daily_event.start_at.astimezone(user_tz).date()
            for day in range(1, num_days + 1):
                calculated_date = date(year, month, day)
                if start_day <= calculated_date and not is_canceled(daily_event, calculated_date):
                    event_dict[day] += 1

        return event_dict

    @staticmethod
    async def get_current_day_events_by_user(
        user_id: int,
        month: int,
        year: int,
        day: int,
        tz_name: str = config.DEFAULT_TIMEZONE_NAME,
        deleted: bool = False,
        platform: str | None = None,
    ) -> str | list:
        user_tz = ZoneInfo(tz_name)
        pickup_date_local = date(year, month, day)
        _, num_days = monthrange(year, month)
        add_days = 4 if day == num_days else 0

        day_start_local = datetime(year, month, day, 0, 0, 0, tzinfo=user_tz)
        day_end_local = datetime(year, month, day, 23, 59, 59, tzinfo=user_tz)

        day_start_utc = day_start_local.astimezone(timezone.utc)
        day_end_utc = day_end_local.astimezone(timezone.utc)

        day_start_for_monthly = 1 if day_start_utc.day > day_end_utc.day else day_start_utc.day

        event_user_col = DBController._event_user_column(platform)
        async with AsyncSessionLocal() as session:
            user_row_id = await DBController._resolve_user_row_id_by_external(user_id, platform, session)
            if user_row_id is None:
                return [] if deleted else ""
            query = select(DbEvent).where(
                event_user_col == user_row_id,
                DbEvent.start_at <= day_end_utc,
                or_(
                    and_(
                        DbEvent.single_event.is_(True),
                        DbEvent.start_at >= day_start_utc,
                    ),
                    DbEvent.daily.is_(True),
                    and_(DbEvent.weekly.is_not(None), DbEvent.weekly.in_([day_start_utc.weekday(), day_end_utc.weekday()])),
                    and_(
                        DbEvent.monthly.is_not(None),
                        or_(
                            DbEvent.monthly.in_(range(day_start_for_monthly, day_end_utc.day + 1 + add_days)),
                            DbEvent.monthly == day_start_utc.day,
                        ),
                    ),
                    and_(
                        DbEvent.annual_day.is_not(None),
                        DbEvent.annual_day.in_([day_start_utc.day, day_end_utc.day]),
                        DbEvent.annual_month.in_([day_start_utc.month, day_end_utc.month]),
                    ),
                ),
            )

            events = (await session.execute(query)).scalars().all()

        event_list = []

        def is_canceled(event: DbEvent) -> bool:
            return pickup_date_local in {_ev.cancel_date for _ev in event.canceled_events}

        for event in events:
            if is_canceled(event):
                continue

            event_start_local_dt = event.start_at.astimezone(user_tz)

            event_stop_local_time = None
            if event.stop_at:
                event_stop_local_time = event.stop_at.astimezone(user_tz).time()
            emoji_prefix = f"{event.emoji} " if event.emoji else ""
            time_range = (
                f"{event_start_local_dt.time().strftime('%H:%M')}-{event_stop_local_time.strftime('%H:%M')}"
                if event_stop_local_time
                else f"{event_start_local_dt.time().strftime('%H:%M')}"
            )

            if event.daily:
                recurrent = f"({Recurrent.daily.get_name().lower()})"
            elif event.weekly is not None:
                if event_start_local_dt.weekday() != day_start_local.weekday():
                    continue
                recurrent = f"({Recurrent.weekly.get_name().lower()})"
            elif event.monthly is not None:
                if event_start_local_dt.day not in range(day_start_local.day, day_start_local.day + 1 + add_days):
                    continue
                recurrent = f"({Recurrent.monthly.get_name().lower()})"
            elif event.annual_day is not None:
                if event_start_local_dt.day != day_start_local.day or event_start_local_dt.month != day_start_local.month:
                    continue
                recurrent = f"({Recurrent.annual.get_name().lower()})"
            else:
                recurrent = ""

            if deleted:
                event_list.append(
                    (
                        f"{emoji_prefix}{time_range}\n"
                        f"{event.description[:20]}",
                        event.id,
                        event.single_event,
                    )
                )
            else:
                prefix = f"{emoji_prefix}{time_range} {recurrent}".strip()
                event_list.append(f"{prefix} - {event.description}")

        event_list.sort(key=lambda x: x[0] if isinstance(x, tuple) else x)

        return event_list if deleted else "\n".join(event_list)

    @staticmethod
    async def delete_all_events_by_user(user_id: int, platform: str | None = None) -> None:
        event_user_col = DBController._event_user_column(platform)
        async with AsyncSessionLocal() as session:
            user_row_id = await DBController._resolve_user_row_id_by_external(user_id, platform, session)
            if user_row_id is None:
                return
            query = delete(DbEvent).where(event_user_col == user_row_id)
            await session.execute(query)
            await session.commit()

    @staticmethod
    async def delete_event_by_id(
        event_id: int | str,
        tz_name: str = config.DEFAULT_TIMEZONE_NAME,
    ) -> tuple:
        user_tz = ZoneInfo(tz_name)
        query = delete(DbEvent).where(DbEvent.id == int(event_id)).returning(DbEvent)
        async with AsyncSessionLocal() as session:
            result = (await session.execute(query)).scalar_one_or_none()
            await session.commit()

            return result.single_event, f"{result.start_at.astimezone(user_tz).time().strftime('%H:%M')} {result.description}"

    async def get_nearest_events(
        self,
        user_id: int,
        tz_name: str = config.DEFAULT_TIMEZONE_NAME,
        platform: str | None = None,
    ) -> list:
        user_tz = ZoneInfo(tz_name)

        start_local = datetime.now(user_tz)
        stop_local = start_local + timedelta(days=NEAREST_EVENTS_DAYS)

        start_dt_utc = start_local.astimezone(timezone.utc)
        stop_dt_utc = stop_local.astimezone(timezone.utc)

        event_user_col = self._event_user_column(platform)
        async with AsyncSessionLocal() as session:
            user_row_id = await self._resolve_user_row_id_by_external(user_id, platform, session)
            if user_row_id is None:
                return []
            query = (
                select(DbEvent)
                .where(
                    event_user_col == user_row_id,
                    DbEvent.start_at <= stop_dt_utc,
                    or_(
                        and_(DbEvent.single_event.is_(True), DbEvent.start_at.between(start_dt_utc, stop_dt_utc)),
                        DbEvent.daily.is_(True),  # Все ежедневные события
                        DbEvent.weekly.is_not(None),  # Все еженедельные события ТК у нас 10 дней, то любое недельное событие попадает
                        and_(
                            DbEvent.monthly.is_not(None),  # Все ежемесячные события, если совпал день
                            DbEvent.monthly.between(start_dt_utc.day, stop_dt_utc.day),
                        ),
                        and_(
                            DbEvent.annual_day.between(start_dt_utc.day, stop_dt_utc.day),
                            DbEvent.annual_month.in_([start_dt_utc.month, stop_dt_utc.month]),
                        ),
                    ),
                )
                .order_by(DbEvent.start_time)
            )

            result = (await session.execute(query)).scalars().all()

            event_list = []

            for event in result:
                _event_start_at_user_tz = event.start_at.astimezone(user_tz)

                if event.single_event is True:
                    event_list.append({_event_start_at_user_tz: (event.description, event.emoji)})

                elif event.daily is True:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_local + timedelta(days=_date)
                        if _calculated_date.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        _combined = datetime.combine(_calculated_date.date(), _event_start_at_user_tz.time(), tzinfo=user_tz)
                        event_list.append({_combined: (event.description, event.emoji)})

                elif event.monthly is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_local + timedelta(days=_date)
                        if _calculated_date.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue

                        effective_day = self.get_effective_month_day(
                            _calculated_date.year, _calculated_date.month, _event_start_at_user_tz.day
                        )
                        if _calculated_date.day == effective_day:
                            _combined = datetime.combine(_calculated_date.date(), _event_start_at_user_tz.time(), tzinfo=user_tz)
                            event_list.append({_combined: (event.description, event.emoji)})

                elif event.annual_day is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_local + timedelta(days=_date)
                        if _calculated_date.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        if _event_start_at_user_tz.day == _calculated_date.day and _event_start_at_user_tz.month == _calculated_date.month:
                            _combined = datetime.combine(_calculated_date.date(), _event_start_at_user_tz.time(), tzinfo=user_tz)
                            event_list.append({_combined: (event.description, event.emoji)})
                            break

                elif event.weekly is not None:
                    for _date in range(0, NEAREST_EVENTS_DAYS):
                        _calculated_date = start_local + timedelta(days=_date)
                        if _calculated_date.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                            continue
                        if _event_start_at_user_tz.weekday() == _calculated_date.weekday() and _event_start_at_user_tz < _calculated_date:
                            _combined = datetime.combine(_calculated_date.date(), _event_start_at_user_tz.time(), tzinfo=user_tz)
                            event_list.append({_combined: (event.description, event.emoji)})

            if event_list:
                event_list = sorted(event_list, key=lambda d: list(d.keys())[0])
            return event_list

    @staticmethod
    async def create_cancel_event(event_id: int, cancel_date: date) -> None:
        new_cancel_event = CanceledEvent(cancel_date=cancel_date, event_id=int(event_id))
        async with AsyncSessionLocal() as session:
            session.add(new_cancel_event)
            await session.commit()

    @staticmethod
    async def get_current_day_events_all_users(
        event_dt: datetime,
        session: AsyncSession,
        limit: int = 400,
        offset: int = 0,
        platform: str | None = None,
    ) -> list:
        last_day = monthrange(event_dt.year, event_dt.month)[1]
        monthly_clause = DbEvent.monthly == event_dt.day
        if event_dt.day == last_day:
            monthly_clause = or_(monthly_clause, DbEvent.monthly > last_day)

        logger.info(f"events for day from db: {event_dt}, week: {event_dt.weekday()}")
        logger.info(f"INCOME DATETIME: {event_dt}")

        event_user_col = DBController._event_user_column(platform)
        query = (
            select(DbEvent)
            .where(
                DbEvent.start_at <= event_dt,
                DbEvent.start_time == event_dt.time(),
                or_(
                    and_(DbEvent.single_event.is_(True), DbEvent.start_at == event_dt),
                    DbEvent.daily.is_(True),  # Все ежедневные события
                    DbEvent.weekly == event_dt.weekday(),  # Все еженедельные события
                    monthly_clause,  # Все ежемесячные события, если совпал день
                    and_(
                        DbEvent.annual_day == event_dt.day,  # Все ежегодные, если совпал месяц и день
                        DbEvent.annual_month == event_dt.month,
                    ),
                ),
            )
            .order_by(DbEvent.start_time)
            .limit(limit)
            .offset(offset)
        )

        event_list = []
        # {"tg_id": "", "start_time": "", "description": ""}

        result = (await session.execute(query)).scalars().all()

        user_ids = [int(getattr(event, event_user_col.key)) for event in result if getattr(event, event_user_col.key) is not None]
        user_col = DBController._user_id_column(platform)
        users_query = select(DB_User).where(DB_User.id.in_(user_ids))
        users = (await session.execute(users_query)).scalars().all()

        users_dict: dict[int, timedelta] = {}
        external_ids: dict[int, int] = {}

        dt_aware_default = datetime.now(ZoneInfo(config.DEFAULT_TIMEZONE_NAME)).utcoffset()

        for _user in users:
            tz = ZoneInfo(_user.time_zone) if _user.time_zone else ZoneInfo(config.DEFAULT_TIMEZONE_NAME)
            dt_aware = datetime.now(tz)
            users_dict[int(_user.id)] = dt_aware.utcoffset()
            external_id = getattr(_user, user_col.key)
            if external_id is not None:
                external_ids[int(_user.id)] = int(external_id)

        for event in result:
            if event_dt.date() in [_ev.cancel_date for _ev in event.canceled_events]:
                continue
            owner_row_id = getattr(event, event_user_col.key)
            if owner_row_id is None:
                continue
            owner_external_id = external_ids.get(int(owner_row_id))
            if owner_external_id is None:
                continue

            event_list.append(
                {
                    "event_id": event.id,
                    "tg_id": owner_external_id,
                    "start_time": (event.start_at + users_dict.get(int(owner_row_id), dt_aware_default)).time(),
                    "description": event.description,
                }
            )

        return event_list

    @staticmethod
    async def resave_event_to_participant(event_id: int, user_id: int, platform: str | None = None) -> int | None:
        async with AsyncSessionLocal() as session:
            query = select(DbEvent).where(DbEvent.id == event_id)
            event = (await session.execute(query)).scalar_one_or_none()

            if not event:
                return None

            creator_tg_id = event.creator_tg_id or event.tg_id
            creator_max_id = event.creator_max_id or event.max_id
            participant_user_row = await DBController._resolve_user_row_id_by_external(user_id, platform, session)
            if participant_user_row is None:
                user_col = DBController._user_id_column(platform).key
                new_user = DB_User(**{user_col: int(user_id)})
                session.add(new_user)
                await session.flush()
                participant_user_row = int(new_user.id)
            participant_user = (
                await session.execute(select(DB_User).where(DB_User.id == participant_user_row))
            ).scalar_one_or_none()
            new_event = DbEvent(
                description=event.description,
                emoji=event.emoji,
                start_time=event.start_time,
                start_at=event.start_at,
                stop_at=event.stop_at,
                single_event=event.single_event,
                daily=event.daily,
                weekly=event.weekly,
                monthly=event.monthly,
                annual_day=event.annual_day,
                annual_month=event.annual_month,
                tg_id=participant_user.tg_id if participant_user else event.tg_id,
                max_id=participant_user.max_id if participant_user else event.max_id,
                creator_tg_id=creator_tg_id,
                creator_max_id=creator_max_id,
                user_id=participant_user_row,
                creator_user_id=event.creator_user_id or event.user_id,
            )

            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)

            return new_event.id

    @staticmethod
    async def reschedule_event(event_id: int, shift_hours: int = 0, shift_days: int = 0) -> int | None:
        async with AsyncSessionLocal() as session:
            event = (await session.execute(select(DbEvent).where(DbEvent.id == int(event_id)))).scalar_one_or_none()
            if not event:
                return None

            delta = timedelta(hours=shift_hours, days=shift_days)
            new_start_at = event.start_at + delta
            new_stop_at = event.stop_at + delta if event.stop_at else None

            new_event = DbEvent(
                description=event.description,
                start_time=new_start_at.time(),
                start_at=new_start_at,
                stop_at=new_stop_at,
                single_event=True,
                daily=False,
                weekly=None,
                monthly=None,
                annual_day=None,
                annual_month=None,
                tg_id=event.tg_id,
                max_id=event.max_id,
                creator_tg_id=event.creator_tg_id or event.tg_id,
                creator_max_id=event.creator_max_id or event.max_id,
                user_id=event.user_id,
                creator_user_id=event.creator_user_id or event.user_id,
            )

            session.add(new_event)
            await session.commit()
            await session.refresh(new_event)

            return new_event.id


db_controller = DBController()
