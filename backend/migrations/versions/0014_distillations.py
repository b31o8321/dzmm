"""distillations table for the v1.7.0 asset distillation MVP

Revision ID: 0014_distillations
Revises: 0013_director_notes
Create Date: 2026-09-28
"""

from sqlalchemy import text
from alembic import op

revision = "0014_distillations"
down_revision = "0013_director_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS distillations (
                run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (run_id, kind)
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS distillations"))
