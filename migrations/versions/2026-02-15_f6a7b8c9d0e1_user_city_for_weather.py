"""user city for weather

Revision ID: f6a7b8c9d0e1
Revises: c1d2e3f4a5b6
Create Date: 2026-02-15 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("tg_users") as batch_op:
        batch_op.add_column(sa.Column("city", sa.String(length=120), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("tg_users") as batch_op:
        batch_op.drop_column("city")
