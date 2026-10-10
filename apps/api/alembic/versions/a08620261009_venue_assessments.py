"""Owner-scoped, append-only annual venue assessment records."""

from alembic import context, op
import sqlalchemy as sa

revision = "a08620261009"
down_revision = "a08520261009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "venue_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("scheme", sa.String(24), nullable=False),
        sa.Column("metric_year", sa.Integer(), nullable=False),
        sa.Column("edition_year", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(240), nullable=False),
        sa.Column("rank_value", sa.String(24), nullable=True),
        sa.Column("impact_factor", sa.Numeric(9, 3), nullable=True),
        sa.Column("is_top", sa.Boolean(), nullable=True),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("source_label", sa.String(240), nullable=False),
        sa.Column("source_kind", sa.String(24), nullable=False),
        sa.Column(
            "checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.UniqueConstraint("user_id", "request_key", name="uq_venue_assessment_request"),
        sa.CheckConstraint(
            "scheme IN ('JCR','CAS','CCF','INDEX','TOP_CONFERENCE')",
            name="ck_venue_assessment_scheme",
        ),
        sa.CheckConstraint(
            "metric_year >= 1900 AND metric_year <= 2200", name="ck_venue_assessment_year"
        ),
        sa.CheckConstraint(
            "impact_factor IS NULL OR (scheme = 'JCR' AND impact_factor >= 0 AND impact_factor <= 1000)",
            name="ck_venue_assessment_jif",
        ),
        sa.CheckConstraint("source_kind = 'OWNER_REPORTED'", name="ck_venue_assessment_source"),
        sa.CheckConstraint(
            "(scheme='JCR' AND (rank_value IS NULL OR rank_value IN ('Q1','Q2','Q3','Q4'))) OR (scheme='CAS' AND rank_value IS NOT NULL AND rank_value IN ('1','2','3','4')) OR (scheme='CCF' AND rank_value IS NOT NULL AND rank_value IN ('A','B','C')) OR (scheme='INDEX' AND rank_value IS NOT NULL AND rank_value IN ('SCIE','SSCI','ESCI','AHCI')) OR (scheme='TOP_CONFERENCE' AND rank_value IS NULL)",
            name="ck_venue_assessment_rank",
        ),
        sa.CheckConstraint(
            "scheme != 'JCR' OR rank_value IS NOT NULL OR impact_factor IS NOT NULL",
            name="ck_venue_assessment_jcr_value",
        ),
        sa.CheckConstraint(
            "(scheme IN ('CAS','TOP_CONFERENCE') OR is_top IS NULL) AND (scheme != 'TOP_CONFERENCE' OR is_top IS NOT NULL)",
            name="ck_venue_assessment_top",
        ),
    )
    op.create_index("ix_venue_assessments_user_id", "venue_assessments", ["user_id"])
    op.create_index("ix_venue_assessments_venue_id", "venue_assessments", ["venue_id"])


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "Online emptiness verification is required before removing venue history"
        )
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM venue_assessments")):
        raise RuntimeError("Export venue assessment history first; populated data is preserved")
    op.drop_index("ix_venue_assessments_venue_id", table_name="venue_assessments")
    op.drop_index("ix_venue_assessments_user_id", table_name="venue_assessments")
    op.drop_table("venue_assessments")
