"""Persist opt-in Zotero automatic ingest policy and schedule.

Revision ID: a03720260929
Revises: f1a920260929
"""

import sqlalchemy as sa
from alembic import op

revision = "a03720260929"
down_revision = "f1a920260929"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_settings",
        sa.Column("auto_copy_pdf", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "analysis_settings",
        sa.Column("auto_sync_interval_minutes", sa.Integer(), server_default="60", nullable=False),
    )
    op.add_column(
        "analysis_settings", sa.Column("auto_sync_next_run_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "analysis_settings", sa.Column("auto_sync_last_run_at", sa.DateTime(timezone=True))
    )
    op.add_column("analysis_settings", sa.Column("auto_sync_last_error", sa.Text()))


def downgrade() -> None:
    op.drop_column("analysis_settings", "auto_sync_last_error")
    op.drop_column("analysis_settings", "auto_sync_last_run_at")
    op.drop_column("analysis_settings", "auto_sync_next_run_at")
    op.drop_column("analysis_settings", "auto_sync_interval_minutes")
    op.drop_column("analysis_settings", "auto_copy_pdf")
