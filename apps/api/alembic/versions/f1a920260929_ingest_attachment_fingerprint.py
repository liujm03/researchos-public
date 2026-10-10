"""Distinguish Zotero PDF child revisions in ingest idempotency.

Revision ID: f1a920260929
Revises: e2a920260929
"""

import sqlalchemy as sa

from alembic import op

revision = "f1a920260929"
down_revision = "e2a920260929"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "literature_ingest_jobs",
        sa.Column("attachment_fingerprint", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("literature_ingest_jobs", "attachment_fingerprint")
