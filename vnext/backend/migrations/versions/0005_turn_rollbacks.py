"""turn rollback audit fields

Revision ID: 0005_turn_rollbacks
Revises: 0004_run_model_profile
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_turn_rollbacks"
down_revision = "0004_run_model_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.add_column(
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="turn")
        )
        batch.add_column(sa.Column("rollback_target_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_turns_rollback_target",
            "turns",
            ["rollback_target_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("turns") as batch:
        batch.drop_constraint("fk_turns_rollback_target", type_="foreignkey")
        batch.drop_column("rollback_target_id")
        batch.drop_column("kind")
