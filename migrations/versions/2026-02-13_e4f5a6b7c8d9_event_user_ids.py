"""events and participants owner by internal user id

Revision ID: e4f5a6b7c8d9
Revises: d2e3f4a5b6c7
Create Date: 2026-02-13 14:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("events", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("creator_user_id", sa.Integer(), nullable=True))
    op.add_column("event_participants", sa.Column("participant_user_id", sa.Integer(), nullable=True))

    conn = op.get_bind()

    # Ensure user rows exist for legacy tg/max ids referenced by events/participants.
    conn.execute(
        sa.text(
            """
            INSERT INTO tg_users (tg_id)
            SELECT DISTINCT src.tg_id
            FROM (
                SELECT tg_id AS tg_id FROM events WHERE tg_id IS NOT NULL
                UNION
                SELECT creator_tg_id AS tg_id FROM events WHERE creator_tg_id IS NOT NULL
                UNION
                SELECT participant_tg_id AS tg_id FROM event_participants WHERE participant_tg_id IS NOT NULL
            ) AS src
            WHERE src.tg_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM tg_users WHERE tg_users.tg_id = src.tg_id
              )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO tg_users (max_id)
            SELECT DISTINCT src.max_id
            FROM (
                SELECT max_id AS max_id FROM events WHERE max_id IS NOT NULL
                UNION
                SELECT creator_max_id AS max_id FROM events WHERE creator_max_id IS NOT NULL
                UNION
                SELECT participant_max_id AS max_id FROM event_participants WHERE participant_max_id IS NOT NULL
            ) AS src
            WHERE src.max_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM tg_users WHERE tg_users.max_id = src.max_id
              )
            """
        )
    )

    # Backfill event owner.
    conn.execute(
        sa.text(
            """
            UPDATE events
            SET user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.tg_id = events.tg_id
                LIMIT 1
            )
            WHERE user_id IS NULL AND events.tg_id IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE events
            SET user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.max_id = events.max_id
                LIMIT 1
            )
            WHERE user_id IS NULL AND events.max_id IS NOT NULL
            """
        )
    )

    # Backfill event creator.
    conn.execute(
        sa.text(
            """
            UPDATE events
            SET creator_user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.tg_id = events.creator_tg_id
                LIMIT 1
            )
            WHERE creator_user_id IS NULL AND events.creator_tg_id IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE events
            SET creator_user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.max_id = events.creator_max_id
                LIMIT 1
            )
            WHERE creator_user_id IS NULL AND events.creator_max_id IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE events
            SET creator_user_id = user_id
            WHERE creator_user_id IS NULL AND user_id IS NOT NULL
            """
        )
    )

    # Backfill participants.
    conn.execute(
        sa.text(
            """
            UPDATE event_participants
            SET participant_user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.tg_id = event_participants.participant_tg_id
                LIMIT 1
            )
            WHERE participant_user_id IS NULL AND event_participants.participant_tg_id IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE event_participants
            SET participant_user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.max_id = event_participants.participant_max_id
                LIMIT 1
            )
            WHERE participant_user_id IS NULL AND event_participants.participant_max_id IS NOT NULL
            """
        )
    )

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.create_index(op.f("ix_events_user_id"), ["user_id"], unique=False)
        batch_op.create_index(op.f("ix_events_creator_user_id"), ["creator_user_id"], unique=False)
        batch_op.create_foreign_key("fk_events_user_id_tg_users", "tg_users", ["user_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key(
            "fk_events_creator_user_id_tg_users", "tg_users", ["creator_user_id"], ["id"], ondelete="SET NULL"
        )

    with op.batch_alter_table("event_participants", schema=None) as batch_op:
        batch_op.create_index(op.f("ix_event_participants_participant_user_id"), ["participant_user_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_event_participants_user_id_tg_users",
            "tg_users",
            ["participant_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("event_participants", schema=None) as batch_op:
        batch_op.drop_constraint("fk_event_participants_user_id_tg_users", type_="foreignkey")
        batch_op.drop_index(op.f("ix_event_participants_participant_user_id"))
        batch_op.drop_column("participant_user_id")

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.drop_constraint("fk_events_creator_user_id_tg_users", type_="foreignkey")
        batch_op.drop_constraint("fk_events_user_id_tg_users", type_="foreignkey")
        batch_op.drop_index(op.f("ix_events_creator_user_id"))
        batch_op.drop_index(op.f("ix_events_user_id"))
        batch_op.drop_column("creator_user_id")
        batch_op.drop_column("user_id")

