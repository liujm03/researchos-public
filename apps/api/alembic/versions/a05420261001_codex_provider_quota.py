"""Owner-selectable Codex account quota without application Token stops."""

from alembic import op
import sqlalchemy as sa

revision = "a05420261001"
down_revision = "a05320261001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("analysis_settings") as batch:
        batch.add_column(sa.Column("budget_mode", sa.String(24), nullable=False,
                                   server_default="LOCAL_LIMITS"))
        batch.create_check_constraint("ck_analysis_budget_mode",
                                      "budget_mode IN ('LOCAL_LIMITS', 'PROVIDER_QUOTA')")


def downgrade() -> None:
    with op.batch_alter_table("analysis_settings") as batch:
        batch.drop_constraint("ck_analysis_budget_mode", type_="check")
        batch.drop_column("budget_mode")
