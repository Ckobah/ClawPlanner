"""event participants

Revision ID: a1b2c3d4e5f6
Revises: e32bd3dd1d45
Create Date: 2026-01-19 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "e32bd3dd1d45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "event_participants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE")),
        sa.Column("participant_tg_id", sa.BigInteger(), nullable=False, comment="ID участника"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_event_participants_event_id", "event_participants", ["event_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_event_participants_event_id", table_name="event_participants")
    op.drop_table("event_participants")
