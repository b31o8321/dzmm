"""record local lifecycle command audit events

Revision ID: 0009_lifecycle_audit_events
Revises: 0008_lorebook_content_contract
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_lifecycle_audit_events"
down_revision = "0008_lorebook_content_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("world_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lifecycle_audit_events")
