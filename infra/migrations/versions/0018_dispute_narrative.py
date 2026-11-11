"""Dispute packet reason code and cited narrative (Dispute Packet Preparer).

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"


def upgrade() -> None:
    op.execute(
        """
        alter table dispute_packets
            add column reason_code text check (reason_code in ('unauthorized',
                'goods_not_received', 'quantity_mismatch', 'amount_mismatch', 'duplicate')),
            add column narrative jsonb;
        """
    )


def downgrade() -> None:
    op.execute("alter table dispute_packets drop column narrative, drop column reason_code;")
