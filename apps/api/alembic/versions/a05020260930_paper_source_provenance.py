"""Add optional payload fingerprint and source timestamp to paper sources.

Revision ID: a05020260930
Revises: a04920260930
"""

import sqlalchemy as sa

from alembic import op

revision = "a05020260930"
down_revision = "a04920260930"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("paper_sources", sa.Column("payload_sha256", sa.String(length=64), nullable=True))
    op.add_column(
        "paper_sources", sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("paper_sources", "source_updated_at")
    op.drop_column("paper_sources", "payload_sha256")
