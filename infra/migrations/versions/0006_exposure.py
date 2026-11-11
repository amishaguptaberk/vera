"""Exposure: distinguish issued (pending) from finalized (confirmed) credit on cases.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute(
        """
        alter table cases
            add column credit_status text
                check (credit_status in ('issued', 'finalized')),
            add column credit_finalized_at timestamptz;
        update cases set credit_status = 'issued' where credit_cents > 0;
        alter table cases add constraint cases_credit_status_present
            check ((credit_cents = 0) = (credit_status is null));
        alter table cases add constraint cases_credit_finalized_at_present
            check ((credit_status = 'finalized') = (credit_finalized_at is not null));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table cases
            drop constraint cases_credit_finalized_at_present,
            drop constraint cases_credit_status_present,
            drop column credit_finalized_at,
            drop column credit_status;
        """
    )
