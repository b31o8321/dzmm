"""model profile edit delete and default selection

Revision ID: 0011_model_management
Revises: 0010_run_lifecycle
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_model_management"
down_revision = "0010_run_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_profiles") as batch:
        batch.add_column(
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.execute(
        "UPDATE model_profiles SET is_default = 1 WHERE id = "
        "(SELECT id FROM model_profiles ORDER BY created_at, id LIMIT 1)"
    )


def downgrade() -> None:
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_column("is_default")
