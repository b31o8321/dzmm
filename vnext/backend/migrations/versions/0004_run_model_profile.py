"""associate runs with model profiles

Revision ID: 0004_run_model_profile
Revises: 0003_model_profiles
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_run_model_profile"
down_revision = "0003_model_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("model_profile_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_runs_model_profiles",
            "model_profiles",
            ["model_profile_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("fk_runs_model_profiles", type_="foreignkey")
        batch.drop_column("model_profile_id")
