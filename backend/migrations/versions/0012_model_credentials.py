"""store only operating-system credential references for model profiles

Revision ID: 0012_model_credentials
Revises: 0011_model_management
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_model_credentials"
down_revision = "0011_model_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("model_profiles") as batch:
        batch.add_column(sa.Column("api_key_ref", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("model_profiles") as batch:
        batch.drop_column("api_key_ref")
