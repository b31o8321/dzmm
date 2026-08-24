"""narrative ruleset contract v2

Revision ID: 0007_narrative_ruleset_contract
Revises: 0005_turn_rollbacks
Create Date: 2026-08-17
"""

from alembic import op

revision = "0007_narrative_ruleset_contract"
down_revision = "0005_turn_rollbacks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE schema_meta SET value = '2026-08-17' "
        "WHERE key = 'contract_version'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE schema_meta SET value = '2026-08-16' "
        "WHERE key = 'contract_version'"
    )
