"""separate run creation and persisted story beats

Revision ID: 0010_run_lifecycle
Revises: 0009_lifecycle_audit_events
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_run_lifecycle"
down_revision = "0009_lifecycle_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_beats",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "sequence", name="uq_story_beats_run_sequence"),
    )
    op.create_table(
        "run_create_requests",
        sa.Column("request_id", sa.String(length=80), primary_key=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "world_id",
            sa.String(length=36),
            sa.ForeignKey("worlds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("run_create_requests")
    op.drop_table("story_beats")
