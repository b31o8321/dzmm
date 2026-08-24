"""phase 0 baseline

Revision ID: 0001_phase0
Revises:
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_phase0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_meta",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("value", sa.String(length=255), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "schema_meta",
            sa.column("key", sa.String),
            sa.column("value", sa.String),
        ),
        [
            {"key": "app", "value": "dzmm-next"},
            {"key": "api_version", "value": "2"},
            {"key": "contract_version", "value": "2026-08-16"},
        ],
    )


def downgrade() -> None:
    op.drop_table("schema_meta")
