"""Final communication and closure (VER-011): final_messages, case_closures.

Revision ID: 0015
Revises: 0009
"""

from alembic import op

revision = "0015"
down_revision = "0009"


def upgrade() -> None:
    op.execute(
        """
        create table final_messages (
            id text primary key,
            case_id text not null references cases(id),
            body text not null,
            status text not null check (status in ('drafted', 'sent')),
            created_by text not null,
            created_at timestamptz not null,
            updated_at timestamptz not null,
            sent_at timestamptz,
            execution_id bigint
        );
        create index final_messages_case on final_messages (case_id);
        create table case_closures (
            id text primary key,
            case_id text not null unique references cases(id),
            reason text not null,
            outcome text not null,
            monitoring boolean not null,
            evidence_snapshot text not null,
            checklist jsonb not null,
            closed_by text not null,
            closed_at timestamptz not null
        );
        """
    )


def downgrade() -> None:
    op.execute("drop table case_closures; drop table final_messages;")
