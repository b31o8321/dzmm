"""mobile pairing control plane

Revision ID: 0006_mobile_pairing
Revises: 0005_turn_rollbacks
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_mobile_pairing"
down_revision = "0005_turn_rollbacks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mobile_devices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "pairing_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "device_id",
            sa.String(length=36),
            sa.ForeignKey("mobile_devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pairing_requests")
    op.drop_table("mobile_devices")
