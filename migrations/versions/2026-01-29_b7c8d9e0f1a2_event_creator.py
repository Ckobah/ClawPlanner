"""event creator

Revision ID: b7c8d9e0f1a2
Revises: f1a2b3c4d5e6
Create Date: 2026-01-29 22:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("events", sa.Column("creator_tg_id", sa.BigInteger(), nullable=True, comment="Creator tg id"))
    op.execute("UPDATE events SET creator_tg_id = tg_id WHERE creator_tg_id IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events", "creator_tg_id")
