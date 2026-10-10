"""Store bounded Zotero venue field provenance, independently from ratings."""

from alembic import op
import sqlalchemy as sa

revision = "a08720261009"
down_revision = "a08620261009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("zotero_source_items", sa.Column("venue_fields", sa.JSON(), nullable=True))
    op.add_column(
        "zotero_source_items", sa.Column("venue_fields_sha256", sa.String(64), nullable=True)
    )
    op.add_column(
        "zotero_source_items", sa.Column("venue_fields_version", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "zotero_source_items",
        sa.Column("venue_fields_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    from alembic import context

    if context.is_offline_mode():
        raise RuntimeError(
            "Online verification of Zotero venue snapshots is required before downgrade"
        )
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM zotero_source_items WHERE venue_fields_sha256 IS NOT NULL")
    ):
        raise RuntimeError("Export Zotero venue snapshots first; populated metadata is preserved")
    with op.batch_alter_table("zotero_source_items") as batch:
        batch.drop_column("venue_fields_synced_at")
        batch.drop_column("venue_fields_version")
        batch.drop_column("venue_fields_sha256")
        batch.drop_column("venue_fields")
