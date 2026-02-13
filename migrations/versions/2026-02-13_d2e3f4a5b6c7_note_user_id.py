"""note owner to internal user id

Revision ID: d2e3f4a5b6c7
Revises: 9f8e7d6c5b4a
Create Date: 2026-02-13 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "9f8e7d6c5b4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tg_note", sa.Column("user_id", sa.Integer(), nullable=True))

    conn = op.get_bind()

    # Map legacy tg_id notes (Telegram owners).
    conn.execute(
        sa.text(
            """
            UPDATE tg_note
            SET user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.tg_id = tg_note.tg_id
                LIMIT 1
            )
            WHERE user_id IS NULL
            """
        )
    )

    # Map legacy max-only notes stored under negative tg_id = -max_id.
    conn.execute(
        sa.text(
            """
            UPDATE tg_note
            SET user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.max_id = ABS(tg_note.tg_id)
                LIMIT 1
            )
            WHERE user_id IS NULL AND tg_id < 0
            """
        )
    )

    # Compatibility fallback if any notes were stored with positive max_id.
    conn.execute(
        sa.text(
            """
            UPDATE tg_note
            SET user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.max_id = tg_note.tg_id
                LIMIT 1
            )
            WHERE user_id IS NULL
            """
        )
    )

    # Ensure missing owners exist in tg_users, then remap.
    conn.execute(
        sa.text(
            """
            INSERT INTO tg_users (tg_id)
            SELECT DISTINCT tg_note.tg_id
            FROM tg_note
            WHERE tg_note.user_id IS NULL AND tg_note.tg_id >= 0
              AND NOT EXISTS (
                  SELECT 1 FROM tg_users WHERE tg_users.tg_id = tg_note.tg_id
              )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO tg_users (max_id)
            SELECT DISTINCT ABS(tg_note.tg_id)
            FROM tg_note
            WHERE tg_note.user_id IS NULL AND tg_note.tg_id < 0
              AND NOT EXISTS (
                  SELECT 1 FROM tg_users WHERE tg_users.max_id = ABS(tg_note.tg_id)
              )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE tg_note
            SET user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.tg_id = tg_note.tg_id
                LIMIT 1
            )
            WHERE user_id IS NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE tg_note
            SET user_id = (
                SELECT tg_users.id
                FROM tg_users
                WHERE tg_users.max_id = ABS(tg_note.tg_id)
                LIMIT 1
            )
            WHERE user_id IS NULL
            """
        )
    )

    with op.batch_alter_table("tg_note", schema=None) as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(op.f("ix_tg_note_user_id"), ["user_id"], unique=False)
        batch_op.create_foreign_key("fk_tg_note_user_id_tg_users", "tg_users", ["user_id"], ["id"], ondelete="CASCADE")
        batch_op.drop_index(op.f("ix_tg_note_tg_id"))
        batch_op.drop_column("tg_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("tg_note", sa.Column("tg_id", sa.BigInteger(), nullable=True))

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE tg_note
            SET tg_id = (
                SELECT COALESCE(tg_users.tg_id, -tg_users.max_id)
                FROM tg_users
                WHERE tg_users.id = tg_note.user_id
                LIMIT 1
            )
            """
        )
    )

    with op.batch_alter_table("tg_note", schema=None) as batch_op:
        batch_op.alter_column("tg_id", existing_type=sa.BigInteger(), nullable=False)
        batch_op.create_index(op.f("ix_tg_note_tg_id"), ["tg_id"], unique=False)
        batch_op.drop_constraint("fk_tg_note_user_id_tg_users", type_="foreignkey")
        batch_op.drop_index(op.f("ix_tg_note_user_id"))
        batch_op.drop_column("user_id")

