"""Track external paper identities without overwriting user edits.

Revision ID: e5d7c91a2b63
Revises: c91a83e4f211
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5d7c91a2b63"
down_revision: str | Sequence[str] | None = "c91a83e4f211"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("provider_key", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=320), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider_key", "provider_id", name="uq_paper_source_identity"),
    )
    op.create_index("ix_paper_sources_user_id", "paper_sources", ["user_id"])
    op.create_index("ix_paper_sources_paper_id", "paper_sources", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_paper_sources_paper_id", table_name="paper_sources")
    op.drop_index("ix_paper_sources_user_id", table_name="paper_sources")
    op.drop_table("paper_sources")
