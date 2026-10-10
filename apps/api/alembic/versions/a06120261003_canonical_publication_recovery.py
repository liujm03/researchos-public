"""Durable approved-note publication recovery.

Revision ID: a06120261003
Revises: a06020261003
"""

import sqlalchemy as sa

from alembic import op

revision = "a06120261003"
down_revision = "a06020261003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("canonical_analytical_notes") as batch:
        batch.add_column(sa.Column("export_error_code", sa.String(80), nullable=True))
        batch.add_column(
            sa.Column("export_attempt_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("export_retryable", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(
            sa.Column("export_next_retry_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("export_lease_token", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("export_lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.create_check_constraint("ck_canonical_export_attempts", "export_attempt_count >= 0")
        batch.create_check_constraint(
            "ck_canonical_export_lease_pair",
            "(export_lease_token IS NULL AND export_lease_expires_at IS NULL) OR (export_lease_token IS NOT NULL AND export_lease_expires_at IS NOT NULL)",
        )
    # Do not reinterpret an old error or retry a manually stopped/conflicting file.
    op.execute(
        sa.text(
            "UPDATE canonical_analytical_notes SET export_retryable = false WHERE export_status <> 'PENDING'"
        )
    )


def downgrade() -> None:
    # a060 has no lease recovery or SAVING API enum. Preserve candidate/error
    # rather than leaving an apparently running file task after a rollback.
    op.execute(
        sa.text(
            "UPDATE canonical_analytical_notes SET export_status = 'FAILED', export_error = 'File publication interrupted by schema rollback; canonical result retained' WHERE export_status = 'SAVING'"
        )
    )
    with op.batch_alter_table("canonical_analytical_notes") as batch:
        batch.drop_constraint("ck_canonical_export_lease_pair", type_="check")
        batch.drop_constraint("ck_canonical_export_attempts", type_="check")
        for name in (
            "export_error_code",
            "export_attempt_count",
            "export_retryable",
            "export_next_retry_at",
            "export_lease_token",
            "export_lease_expires_at",
        ):
            batch.drop_column(name)
