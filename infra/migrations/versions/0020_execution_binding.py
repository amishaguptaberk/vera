"""Bind a dispute review and a card-admin approval to the evidence snapshot they were given on.

submit_dispute and apply_card_controls refuse when the case's snapshot has moved on since the
review/approval, as issue_provisional_credit already does through the reviewer approval.

Revision ID: 0020
Revises: 0019
"""

from alembic import op

revision = "0020"
down_revision = "0019"


def upgrade() -> None:
    op.execute("alter table dispute_packets add column reviewed_snapshot text")
    op.execute("alter table control_plans add column approved_snapshot text")


def downgrade() -> None:
    op.execute("alter table control_plans drop column approved_snapshot")
    op.execute("alter table dispute_packets drop column reviewed_snapshot")
