"""Add PostgreSQL full-text expression indexes for Phase 1 search.

Revision ID: a04920260930
Revises: a04820260929
"""

import sqlalchemy as sa

from alembic import op

revision = "a04920260930"
down_revision = "a04820260929"
branch_labels = None
depends_on = None


# Keep these expressions identical to the PostgreSQL search query's left operand.
# Explicit coalesce and immutable text concatenation make the expression indexable.
_GIN_INDEXES = (
    (
        "ix_papers_search_simple_gin",
        "papers",
        "to_tsvector('simple'::regconfig, coalesce(title, '') || ' ' || "
        "coalesce(abstract, ''))",
    ),
    (
        "ix_research_projects_search_simple_gin",
        "research_projects",
        "to_tsvector('simple'::regconfig, coalesce(name, '') || ' ' || "
        "coalesce(summary, '') || ' ' || coalesce(problem, '') || ' ' || "
        "coalesce(motivation, '') || ' ' || coalesce(research_gap, ''))",
    ),
    (
        "ix_tasks_search_simple_gin",
        "tasks",
        "to_tsvector('simple'::regconfig, coalesce(title, '') || ' ' || "
        "coalesce(description, ''))",
    ),
    (
        "ix_paper_notes_search_simple_gin",
        "paper_notes",
        "to_tsvector('simple'::regconfig, coalesce(title, '') || ' ' || "
        "coalesce(body_markdown, ''))",
    ),
)


def _postgresql() -> bool:
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if not _postgresql():
        return
    for name, table, expression in _GIN_INDEXES:
        op.create_index(name, table, [sa.text(expression)], postgresql_using="gin")


def downgrade() -> None:
    if not _postgresql():
        return
    for name, table, _expression in reversed(_GIN_INDEXES):
        op.drop_index(name, table_name=table)
