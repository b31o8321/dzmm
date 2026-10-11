"""visual_media for ComfyUI-generated images (v1.11.0 M1)

Revision ID: 0016_visual_media
Revises: 0015_model_context_size
Create Date: 2026-10-11
"""

from alembic import op
from sqlalchemy import text

revision = "0016_visual_media"
down_revision = "0015_model_context_size"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS visual_media (
                id TEXT PRIMARY KEY,
                world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                subject_id TEXT NOT NULL DEFAULT '',
                turn_seq INTEGER,
                file_path TEXT,
                prompt TEXT NOT NULL,
                negative_prompt TEXT,
                seed INTEGER,
                ref_image TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_visual_media_world "
            "ON visual_media (world_id, kind, subject_id)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS visual_media"))
