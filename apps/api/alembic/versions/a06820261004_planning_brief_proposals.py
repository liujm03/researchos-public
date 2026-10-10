"""Literal planning proposals and explicit draft adoption. Revision a06820261004."""

import sqlalchemy as sa
from alembic import op

revision = "a06820261004"
down_revision = "a06720261004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("research_stage_grants") as batch:
        batch.add_column(
            sa.Column(
                "output_contract_version",
                sa.String(64),
                nullable=False,
                server_default="planning-markdown-v1",
            )
        )
        batch.add_column(sa.Column("output_contract_sha256", sa.String(64), nullable=True))
        batch.add_column(
            sa.Column("output_contract_payload", sa.JSON(none_as_null=True), nullable=True)
        )
        batch.create_check_constraint(
            "ck_stage_output_contract_pair",
            "(output_contract_sha256 IS NULL AND output_contract_payload IS NULL AND output_contract_version='planning-markdown-v1') OR (output_contract_sha256 IS NOT NULL AND output_contract_payload IS NOT NULL AND length(output_contract_sha256)=64)",
        )
    with op.batch_alter_table("research_planning_results") as batch:
        batch.add_column(
            sa.Column(
                "normalization_status", sa.String(24), nullable=False, server_default="NOT_RECORDED"
            )
        )
        batch.add_column(sa.Column("normalization_issue", sa.String(120), nullable=True))
        batch.create_unique_constraint(
            "uq_planning_result_owner", ["job_id", "project_id", "user_id"]
        )
        batch.create_check_constraint(
            "ck_planning_result_normalization",
            "normalization_status IN ('AVAILABLE','UNUSABLE','NOT_REQUESTED','NOT_RECORDED','QUARANTINED')",
        )
    with op.batch_alter_table("research_briefs") as batch:
        batch.add_column(sa.Column("stop_rules_origin", sa.String(24), nullable=True))
        batch.add_column(sa.Column("stop_source_planning_job_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("stop_source_result_sha256", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_brief_stop_planning_owner",
            "research_planning_jobs",
            ["stop_source_planning_job_id", "project_id", "user_id"],
            ["id", "project_id", "user_id"],
        )
        batch.create_check_constraint(
            "ck_brief_stop_origin",
            "stop_rules_origin IS NULL OR stop_rules_origin IN ('OWNER_INPUT','AI_INFERRED')",
        )
        batch.create_check_constraint(
            "ck_brief_stop_source_pair",
            "(stop_source_planning_job_id IS NULL AND stop_source_result_sha256 IS NULL) OR (stop_source_planning_job_id IS NOT NULL AND stop_source_result_sha256 IS NOT NULL AND length(stop_source_result_sha256)=64)",
        )
    with op.batch_alter_table("research_brief_sections") as batch:
        batch.add_column(sa.Column("source_planning_job_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("source_result_sha256", sa.String(64), nullable=True))
        batch.drop_constraint("ck_brief_section_origin", type_="check")
        batch.create_check_constraint(
            "ck_brief_section_origin",
            "origin_type IN ('OWNER_INPUT','PROJECT_CONTEXT','MISSING','AI_INFERRED')",
        )
        batch.create_foreign_key(
            "fk_brief_section_planning_owner",
            "research_planning_jobs",
            ["source_planning_job_id", "project_id", "user_id"],
            ["id", "project_id", "user_id"],
        )
        batch.create_check_constraint(
            "ck_brief_section_source_pair",
            "(source_planning_job_id IS NULL AND source_result_sha256 IS NULL) OR (source_planning_job_id IS NOT NULL AND source_result_sha256 IS NOT NULL AND length(source_result_sha256)=64)",
        )
        batch.create_check_constraint(
            "ck_brief_section_ai_source",
            "origin_type<>'AI_INFERRED' OR source_planning_job_id IS NOT NULL",
        )
    op.create_table(
        "planning_brief_proposals",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("contract_sha256", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("stop_rules_quote", sa.Text(), nullable=True),
        sa.Column("stop_source_start", sa.Integer(), nullable=True),
        sa.Column("stop_source_end", sa.Integer(), nullable=True),
        sa.Column("warnings_text", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "length(result_sha256)=64 AND length(sha256)=64", name="ck_brief_proposal_hashes"
        ),
        sa.CheckConstraint(
            "(stop_rules_quote IS NULL AND stop_source_start IS NULL AND stop_source_end IS NULL) OR (stop_rules_quote IS NOT NULL AND stop_source_start IS NOT NULL AND stop_source_end IS NOT NULL AND stop_source_start>=0 AND stop_source_end>stop_source_start)",
            name="ck_brief_proposal_stop_span",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["attempt_id", "job_id", "project_id", "user_id"],
            [
                "research_planning_attempts.id",
                "research_planning_attempts.job_id",
                "research_planning_attempts.project_id",
                "research_planning_attempts.user_id",
            ],
            name="fk_brief_proposal_attempt_owner",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "research_planning_results.job_id",
                "research_planning_results.project_id",
                "research_planning_results.user_id",
            ],
            name="fk_brief_proposal_result_owner",
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("job_id", "project_id", "user_id", name="uq_brief_proposal_owner"),
    )
    op.create_index(
        "ix_planning_brief_proposals_user_id", "planning_brief_proposals", ["user_id"], unique=False
    )
    op.create_table(
        "planning_brief_proposal_sections",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=24), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source_start", sa.Integer(), nullable=True),
        sa.Column("source_end", sa.Integer(), nullable=True),
        sa.Column("uncertainty", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "key IN ('intent','related_work','hypotheses','resources','routes','protocol','stage_plan','decision')",
            name="ck_brief_proposal_section_key",
        ),
        sa.CheckConstraint(
            "(content IS NULL AND source_start IS NULL AND source_end IS NULL) OR (content IS NOT NULL AND source_start IS NOT NULL AND source_end IS NOT NULL AND source_start>=0 AND source_end>source_start)",
            name="ck_brief_proposal_section_span",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "planning_brief_proposals.job_id",
                "planning_brief_proposals.project_id",
                "planning_brief_proposals.user_id",
            ],
            name="fk_brief_proposal_section_owner",
        ),
        sa.PrimaryKeyConstraint("job_id", "key"),
    )
    op.create_index(
        "ix_planning_brief_proposal_sections_user_id",
        "planning_brief_proposal_sections",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "planning_brief_adoption_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("new_brief_id", sa.Uuid(), nullable=False),
        sa.Column("base_brief_id", sa.Uuid(), nullable=False),
        sa.Column("result_sha256", sa.String(length=64), nullable=False),
        sa.Column("proposal_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("include_stop_rules", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "length(result_sha256)=64 AND length(proposal_sha256)=64 AND length(request_sha256)=64",
            name="ck_brief_adoption_hashes",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["base_brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_adoption_base_owner",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "project_id", "user_id"],
            [
                "research_planning_jobs.id",
                "research_planning_jobs.project_id",
                "research_planning_jobs.user_id",
            ],
            name="fk_brief_adoption_job_owner",
        ),
        sa.ForeignKeyConstraint(
            ["new_brief_id", "project_id", "user_id"],
            ["research_briefs.id", "research_briefs.project_id", "research_briefs.user_id"],
            name="fk_brief_adoption_new_owner",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "project_id", "idempotency_key", name="uq_brief_adoption_key"
        ),
        sa.UniqueConstraint("new_brief_id", name="uq_brief_adoption_revision"),
    )
    op.create_index(
        "ix_planning_brief_adoption_receipts_user_id",
        "planning_brief_adoption_receipts",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Unchecked offline downgrade is unsupported; verify the target owner data online"
        )
    checks = (
        "SELECT COUNT(*) FROM research_stage_grants WHERE output_contract_sha256 IS NOT NULL OR output_contract_payload IS NOT NULL OR output_contract_version <> 'planning-markdown-v1'",
        "SELECT COUNT(*) FROM research_planning_results WHERE normalization_status NOT IN ('NOT_RECORDED','NOT_REQUESTED') OR normalization_issue IS NOT NULL",
        "SELECT COUNT(*) FROM research_brief_sections WHERE source_planning_job_id IS NOT NULL OR source_result_sha256 IS NOT NULL OR origin_type='AI_INFERRED'",
        "SELECT COUNT(*) FROM research_briefs WHERE stop_rules_origin IS NOT NULL OR stop_source_planning_job_id IS NOT NULL OR stop_source_result_sha256 IS NOT NULL",
        "SELECT COUNT(*) FROM planning_brief_proposals",
        "SELECT COUNT(*) FROM planning_brief_proposal_sections",
        "SELECT COUNT(*) FROM planning_brief_adoption_receipts",
    )
    if any(op.get_bind().scalar(sa.text(query)) for query in checks):
        raise RuntimeError(
            "a068 owner data cannot be represented by a067; preserve backup and restore into an isolated compatible database"
        )
    op.drop_table("planning_brief_adoption_receipts")
    op.drop_table("planning_brief_proposal_sections")
    op.drop_table("planning_brief_proposals")
    with op.batch_alter_table("research_brief_sections") as batch:
        for name, kind in (
            ("fk_brief_section_planning_owner", "foreignkey"),
            ("ck_brief_section_source_pair", "check"),
            ("ck_brief_section_ai_source", "check"),
            ("ck_brief_section_origin", "check"),
        ):
            batch.drop_constraint(name, type_=kind)
        batch.drop_column("source_planning_job_id")
        batch.drop_column("source_result_sha256")
        batch.create_check_constraint(
            "ck_brief_section_origin", "origin_type IN ('OWNER_INPUT','PROJECT_CONTEXT','MISSING')"
        )
    with op.batch_alter_table("research_briefs") as batch:
        batch.drop_constraint("fk_brief_stop_planning_owner", type_="foreignkey")
        batch.drop_constraint("ck_brief_stop_origin", type_="check")
        batch.drop_constraint("ck_brief_stop_source_pair", type_="check")
        for column in (
            "stop_rules_origin",
            "stop_source_planning_job_id",
            "stop_source_result_sha256",
        ):
            batch.drop_column(column)
    with op.batch_alter_table("research_planning_results") as batch:
        batch.drop_constraint("uq_planning_result_owner", type_="unique")
        batch.drop_constraint("ck_planning_result_normalization", type_="check")
        batch.drop_column("normalization_status")
        batch.drop_column("normalization_issue")
    with op.batch_alter_table("research_stage_grants") as batch:
        batch.drop_constraint("ck_stage_output_contract_pair", type_="check")
        for column in (
            "output_contract_version",
            "output_contract_sha256",
            "output_contract_payload",
        ):
            batch.drop_column(column)
