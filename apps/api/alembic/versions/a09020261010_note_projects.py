"""Independent multi-project reading-note classification."""

import sqlalchemy as sa

from alembic import context, op

revision = "a09020261010"
down_revision = "a08920261009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note_project_classifications",
        sa.Column("note_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("note_id", "user_id", name="uq_note_project_classification_owner"),
        sa.ForeignKeyConstraint(
            ["note_id", "user_id"],
            ["paper_research_notes.id", "paper_research_notes.user_id"],
            name="fk_note_classification_owner",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("version >= 1", name="ck_note_project_classification_version"),
    )
    op.create_index(
        "ix_note_project_classifications_user_id", "note_project_classifications", ["user_id"]
    )
    op.create_table(
        "note_projects",
        sa.Column("note_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.ForeignKeyConstraint(
            ["note_id", "user_id"],
            ["note_project_classifications.note_id", "note_project_classifications.user_id"],
            name="fk_note_project_classification_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["research_projects.id", "research_projects.user_id"],
            name="fk_note_project_project_owner",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_note_projects_project_id", "note_projects", ["project_id"])


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Online classification emptiness check required before downgrade")
    for name in ("note_projects", "note_project_classifications"):
        if op.get_bind().scalar(sa.text(f"SELECT COUNT(*) FROM {name}")):
            raise RuntimeError(
                "Export note classification first; populated classification is preserved"
            )
    op.drop_table("note_projects")
    op.drop_table("note_project_classifications")
