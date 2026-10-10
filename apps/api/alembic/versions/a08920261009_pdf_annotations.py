"""Owner and source-bound normalized PDF marks; original PDFs stay immutable."""

import sqlalchemy as sa

from alembic import context, op

revision = "a08920261009"
down_revision = "a08820261009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pdf_annotations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("paper_id", sa.Uuid(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("attachment_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("last_expected_revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["paper_id", "user_id"], ["research_entities.id", "research_entities.user_id"]
        ),
        sa.ForeignKeyConstraint(
            ["attachment_id", "user_id"], ["attachments.id", "attachments.user_id"]
        ),
        sa.UniqueConstraint("id", "user_id", name="uq_pdf_annotation_owner"),
        sa.CheckConstraint(
            "kind IN ('HIGHLIGHT','UNDERLINE','COMMENT','INK')", name="ck_pdf_annotation_kind"
        ),
        sa.CheckConstraint("page >= 1 AND page <= 2000", name="ck_pdf_annotation_page"),
        sa.CheckConstraint("revision >= 1", name="ck_pdf_annotation_revision"),
    )
    op.create_index("ix_pdf_annotations_user_id", "pdf_annotations", ["user_id"])
    op.create_index(
        "ix_pdf_annotation_source",
        "pdf_annotations",
        ["user_id", "paper_id", "attachment_id", "source_sha256"],
    )
    op.create_table(
        "pdf_annotation_geometries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("annotation_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("geometry_kind", sa.String(8), nullable=False),
        sa.Column("x", sa.Float()),
        sa.Column("y", sa.Float()),
        sa.Column("width", sa.Float()),
        sa.Column("height", sa.Float()),
        sa.ForeignKeyConstraint(
            ["annotation_id", "user_id"], ["pdf_annotations.id", "pdf_annotations.user_id"]
        ),
        sa.UniqueConstraint("annotation_id", "position", name="uq_pdf_geometry_position"),
        sa.UniqueConstraint("id", "user_id", name="uq_pdf_geometry_owner"),
        sa.CheckConstraint("geometry_kind IN ('RECT','STROKE')", name="ck_pdf_geometry_kind"),
        sa.CheckConstraint("position >= 0 AND position < 50", name="ck_pdf_geometry_position"),
        sa.CheckConstraint(
            "(geometry_kind='STROKE' AND x IS NULL AND y IS NULL AND width IS NULL AND height IS NULL) OR (geometry_kind='RECT' AND x IS NOT NULL AND y IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL AND x>=0 AND y>=0 AND width>0 AND height>0 AND x+width<=1.000001 AND y+height<=1.000001)",
            name="ck_pdf_geometry_bounds",
        ),
    )
    op.create_index(
        "ix_pdf_annotation_geometries_annotation_id", "pdf_annotation_geometries", ["annotation_id"]
    )
    op.create_table(
        "pdf_annotation_points",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("geometry_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(
            ["geometry_id", "user_id"],
            ["pdf_annotation_geometries.id", "pdf_annotation_geometries.user_id"],
        ),
        sa.UniqueConstraint("geometry_id", "position", name="uq_pdf_point_position"),
        sa.CheckConstraint("position >= 0 AND position < 2000", name="ck_pdf_point_position"),
        sa.CheckConstraint("x>=0 AND x<=1 AND y>=0 AND y<=1", name="ck_pdf_point_bounds"),
    )
    op.create_index(
        "ix_pdf_annotation_points_geometry_id", "pdf_annotation_points", ["geometry_id"]
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Online PDF annotation emptiness check required before downgrade")
    for name in ("pdf_annotation_points", "pdf_annotation_geometries", "pdf_annotations"):
        if op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {name}")):
            raise RuntimeError("Export PDF annotation history first; populated marks are preserved")
    op.drop_table("pdf_annotation_points")
    op.drop_table("pdf_annotation_geometries")
    op.drop_table("pdf_annotations")
