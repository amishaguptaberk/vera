"""Queue display strings for display-only (non-live) cases.

Revision ID: 0008
Revises: 0006
"""

from alembic import op

revision = "0008"
down_revision = "0006"


def upgrade() -> None:
    op.execute(
        """
        alter table cases
            add column display_next_action text,
            add column display_waiting_on text,
            add column display_blocker text;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table cases
            drop column display_blocker,
            drop column display_waiting_on,
            drop column display_next_action;
        """
    )
