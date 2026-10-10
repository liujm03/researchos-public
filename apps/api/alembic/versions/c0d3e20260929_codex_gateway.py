"""Persist owner scoped Codex tasks and audit events.

Revision ID: c0d3e20260929
Revises: a910d6625f3b
"""

from alembic import op
import sqlalchemy as sa

revision = "c0d3e20260929"
down_revision = "a910d6625f3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "codex_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("related_project_id", sa.Uuid(), sa.ForeignKey("research_projects.id")),
        sa.Column(
            "related_research_question_id", sa.Uuid(), sa.ForeignKey("research_questions.id")
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("workspace_id", sa.String(80), nullable=False),
        sa.Column("workspace_path_snapshot", sa.String(2048), nullable=False),
        sa.Column("provider_key", sa.String(64), nullable=False),
        sa.Column("model_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("event_sequence", sa.Integer(), nullable=False),
        sa.Column("worker_lease_id", sa.String(64)),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("codex_thread_id", sa.String(128)),
        sa.Column("codex_turn_id", sa.String(128)),
        sa.Column("base_commit", sa.String(64)),
        sa.Column("diff_summary", sa.Text()),
        sa.Column("final_response", sa.Text()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_codex_task_idempotency"),
    )
    op.create_index("ix_codex_tasks_user_id", "codex_tasks", ["user_id"])
    op.create_index("ix_codex_tasks_owner_status", "codex_tasks", ["user_id", "status"])
    op.create_table(
        "codex_task_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("codex_tasks.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "sequence", name="uq_codex_event_sequence"),
    )
    op.create_index("ix_codex_task_events_task_id", "codex_task_events", ["task_id"])
    op.create_index("ix_codex_task_events_user_id", "codex_task_events", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_codex_task_events_user_id", table_name="codex_task_events")
    op.drop_index("ix_codex_task_events_task_id", table_name="codex_task_events")
    op.drop_table("codex_task_events")
    op.drop_index("ix_codex_tasks_owner_status", table_name="codex_tasks")
    op.drop_index("ix_codex_tasks_user_id", table_name="codex_tasks")
    op.drop_table("codex_tasks")
