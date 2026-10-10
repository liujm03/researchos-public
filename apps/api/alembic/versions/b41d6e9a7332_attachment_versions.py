"""Keep previous Zotero PDF versions when an attachment changes.

Revision ID: b41d6e9a7332
Revises: 0caa5bfbb4f3
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b41d6e9a7332"
down_revision: str | Sequence[str] | None = "0caa5bfbb4f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("paper_attachments") as batch:
        batch.drop_constraint("uq_paper_source_attachment", type_="unique")
        batch.create_unique_constraint(
            "uq_paper_source_attachment", ["source_item_id", "attachment_key", "source_version"]
        )


def downgrade() -> None:
    with op.batch_alter_table("paper_attachments") as batch:
        batch.drop_constraint("uq_paper_source_attachment", type_="unique")
        batch.create_unique_constraint(
            "uq_paper_source_attachment", ["source_item_id", "attachment_key"]
        )
