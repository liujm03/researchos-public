"""Archive cleared literature tasks without deleting research evidence."""

from alembic import op
import sqlalchemy as sa

revision = "a05520261001"
down_revision = "a05420261001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("literature_ingest_jobs", sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("literature_ingest_jobs", "cleared_at")
