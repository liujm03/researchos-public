"""Snapshot Codex task token budget and overrun state.

Revision ID: b0d620260929
Revises: d1ff20260929
"""

from alembic import op
import sqlalchemy as sa

revision = "b0d620260929"
down_revision = "d1ff20260929"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("codex_tasks", sa.Column("max_tokens", sa.Integer(), nullable=True))
    op.add_column(
        "codex_tasks",
        sa.Column(
            "token_budget_exceeded", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("codex_tasks", "token_budget_exceeded")
    op.drop_column("codex_tasks", "max_tokens")
