"""Store a bounded, reviewable Codex workspace patch.

Revision ID: d1ff20260929
Revises: c0d3e20260929
"""

from alembic import op
import sqlalchemy as sa

revision = "d1ff20260929"
down_revision = "c0d3e20260929"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("codex_tasks", sa.Column("diff_patch", sa.Text(), nullable=True))
    op.add_column(
        "codex_tasks",
        sa.Column("diff_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("codex_tasks", "diff_truncated")
    op.drop_column("codex_tasks", "diff_patch")
