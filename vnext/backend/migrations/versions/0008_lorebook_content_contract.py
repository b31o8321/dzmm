"""make interoperable lorebook and character cards the vNext content contract

Revision ID: 0008_lorebook_content_contract
Revises: 0007_narrative_ruleset_contract
Create Date: 2026-08-17
"""

from alembic import op


revision = "0008_lorebook_content_contract"
down_revision = "0007_narrative_ruleset_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE schema_meta SET value = '2026-08-17-content-boundary' "
        "WHERE key = 'contract_version'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE schema_meta SET value = '2026-08-17' "
        "WHERE key = 'contract_version'"
    )
