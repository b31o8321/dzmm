"""director notes for long-line pacing (ADR-012)

Revision ID: 0013_director_notes
Revises: 0012_model_credentials
Create Date: 2026-09-06
"""

from sqlalchemy import text
from alembic import op

revision = "0013_director_notes"
down_revision = "0012_model_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS director_notes (
                run_id TEXT NOT NULL,
                turn INTEGER NOT NULL,
                tension TEXT NOT NULL,
                hook TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (run_id, turn)
            )
            """
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS director_notes"))
