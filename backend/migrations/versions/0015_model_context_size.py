"""model profile context_size for per-model Ollama num_ctx control

Revision ID: 0015_model_context_size
Revises: 0014_distillations
Create Date: 2026-09-30
"""

from sqlalchemy import text
from alembic import op

revision = "0015_model_context_size"
down_revision = "0014_distillations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text(
        "ALTER TABLE model_profiles ADD COLUMN context_size INTEGER"
    ))


def downgrade() -> None:
    op.execute(text("ALTER TABLE model_profiles DROP COLUMN context_size"))
