"""Enforce one owner account per installation.

Revision ID: c91a83e4f211
Revises: 725bbdea6455
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c91a83e4f211"
down_revision: str | Sequence[str] | None = "725bbdea6455"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("single_owner_key", sa.Integer(), server_default="1", nullable=False)
        )
        batch.create_check_constraint("ck_users_single_owner", "single_owner_key = 1")
        batch.create_unique_constraint("uq_users_single_owner_key", ["single_owner_key"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_single_owner_key", type_="unique")
        batch.drop_constraint("ck_users_single_owner", type_="check")
        batch.drop_column("single_owner_key")
