"""phase 1 world aggregate

Revision ID: 0002_phase1
Revises: 0001_phase0
Create Date: 2026-08-16
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_phase1"
down_revision = "0001_phase0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worlds",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "world_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("world_id", sa.String(length=36), sa.ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("world_id", "version_number", name="uq_world_versions_number"),
    )
    op.create_table(
        "heroes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("world_version_id", sa.String(length=36), sa.ForeignKey("world_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("hero_id", sa.String(length=36), sa.ForeignKey("heroes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "turns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String(length=80), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("player_input", sa.Text(), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("commands", sa.JSON(), nullable=False),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("before_revision", sa.Integer(), nullable=False),
        sa.Column("after_revision", sa.Integer(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", "request_id", name="uq_turns_run_request"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_turns_run_sequence"),
    )
    op.create_table(
        "compose_requests",
        sa.Column("request_id", sa.String(length=80), primary_key=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("world_id", sa.String(length=36), sa.ForeignKey("worlds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("compose_requests")
    op.drop_table("turns")
    op.drop_table("runs")
    op.drop_table("heroes")
    op.drop_table("world_versions")
    op.drop_table("worlds")
