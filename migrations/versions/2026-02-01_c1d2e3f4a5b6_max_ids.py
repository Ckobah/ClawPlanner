"""max bot ids

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-02-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("tg_users") as batch_op:
        batch_op.add_column(sa.Column("max_id", sa.BigInteger(), nullable=True))
        batch_op.alter_column("tg_id", existing_type=sa.BigInteger(), nullable=True)
        batch_op.create_unique_constraint("uq_tg_users_max_id", ["max_id"])

    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("max_id", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("creator_max_id", sa.BigInteger(), nullable=True))
        batch_op.alter_column("tg_id", existing_type=sa.BigInteger(), nullable=True)

    with op.batch_alter_table("event_participants") as batch_op:
        batch_op.add_column(sa.Column("participant_max_id", sa.BigInteger(), nullable=True))
        batch_op.alter_column("participant_tg_id", existing_type=sa.BigInteger(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("event_participants") as batch_op:
        batch_op.alter_column("participant_tg_id", existing_type=sa.BigInteger(), nullable=False)
        batch_op.drop_column("participant_max_id")

    with op.batch_alter_table("events") as batch_op:
        batch_op.alter_column("tg_id", existing_type=sa.BigInteger(), nullable=False)
        batch_op.drop_column("creator_max_id")
        batch_op.drop_column("max_id")

    with op.batch_alter_table("tg_users") as batch_op:
        batch_op.drop_constraint("uq_tg_users_max_id", type_="unique")
        batch_op.alter_column("tg_id", existing_type=sa.BigInteger(), nullable=False)
        batch_op.drop_column("max_id")
