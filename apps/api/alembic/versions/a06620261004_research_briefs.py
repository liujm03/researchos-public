"""Immutable research brief revisions and exact owner review receipts. Revision a06620261004."""

import sqlalchemy as sa
from alembic import op

revision = "a06620261004"
down_revision = "a06520261004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("papers") as batch:
        batch.create_unique_constraint("uq_paper_owner", ["id", "user_id"])
    op.create_table(
        "research_briefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("project_version", sa.Integer(), nullable=False),
        sa.Column("base_brief_id", sa.Uuid(), nullable=True),
        sa.Column("idea", sa.Text(), nullable=False),
        sa.Column("stop_rules", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("length(sha256) = 64", name="ck_brief_hash"),
        sa.CheckConstraint("length(idea) BETWEEN 1 AND 12000", name="ck_brief_idea"),
        sa.CheckConstraint("revision > 0 AND project_version > 0", name="ck_brief_versions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["base_brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_base_project_owner",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_brief_project_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", "user_id", name="uq_research_brief_project_owner"),
        sa.UniqueConstraint("project_id", "revision", name="uq_research_brief_revision"),
    )
    op.create_index(
        "ix_research_briefs_project_id", "research_briefs", ["project_id"], unique=False
    )
    op.create_index("ix_research_briefs_user_id", "research_briefs", ["user_id"], unique=False)
    op.create_table(
        "research_brief_sections",
        sa.Column("brief_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=24), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("origin_type", sa.String(length=24), nullable=False),
        sa.Column("uncertainty", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "key IN ('intent','related_work','hypotheses','resources','routes','protocol','stage_plan','decision')",
            name="ck_brief_section_key",
        ),
        sa.CheckConstraint(
            "origin_type IN ('OWNER_INPUT','PROJECT_CONTEXT','MISSING')",
            name="ck_brief_section_origin",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_section_owner",
        ),
        sa.PrimaryKeyConstraint("brief_id", "key"),
    )
    op.create_index(
        "ix_research_brief_sections_user_id", "research_brief_sections", ["user_id"], unique=False
    )
    op.create_table(
        "research_brief_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("brief_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("paper_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=600), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("doi", sa.String(length=300), nullable=True),
        sa.Column("paper_version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "paper_version > 0 AND length(sha256) = 64", name="ck_brief_evidence_version_hash"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_evidence_owner",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id", "user_id"],
            ["papers.id", "papers.user_id"],
            name="fk_brief_evidence_paper_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brief_id", "paper_id", name="uq_brief_evidence_paper"),
    )
    op.create_index(
        "ix_research_brief_evidence_brief_id", "research_brief_evidence", ["brief_id"], unique=False
    )
    op.create_index(
        "ix_research_brief_evidence_user_id", "research_brief_evidence", ["user_id"], unique=False
    )
    op.create_table(
        "research_brief_reviews",
        sa.Column("brief_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("decision IN ('ACCEPT','REJECT')", name="ck_brief_review_decision"),
        sa.CheckConstraint(
            "length(sha256) = 64 AND reviewer_id = user_id", name="ck_brief_review_identity"
        ),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_review_owner",
        ),
        sa.PrimaryKeyConstraint("brief_id"),
    )
    op.create_index(
        "ix_research_brief_reviews_user_id", "research_brief_reviews", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_table("research_brief_reviews")
    op.drop_table("research_brief_evidence")
    op.drop_table("research_brief_sections")
    op.drop_table("research_briefs")
    with op.batch_alter_table("papers") as batch:
        batch.drop_constraint("uq_paper_owner", type_="unique")
