"""Workflow skeleton: adapter executions and demo fault injection.

Both tables are mutable (status / remaining change in place), so neither gets the append-only
trigger from 0001; the audit trail is the adapter.* events in audit_events.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute(
        """
        create table adapter_executions (
            id bigserial primary key,
            case_id text not null references cases(id),
            adapter text not null,
            operation text not null,
            idempotency_key text not null unique,
            request jsonb not null,
            status text not null
                check (status in ('pending', 'succeeded', 'failed', 'uncertain')),
            result jsonb,
            error text,
            attempts integer not null default 0,
            created_at timestamptz not null,
            updated_at timestamptz not null,
            event_id bigint
        );
        create index adapter_executions_case on adapter_executions (case_id);
        create table adapter_faults (
            id bigserial primary key,
            adapter text not null,
            operation text not null,
            mode text not null check (mode in ('fail', 'uncertain', 'timeout')),
            remaining integer not null check (remaining >= 0)
        );
        """
    )


def downgrade() -> None:
    op.execute("drop table adapter_faults; drop table adapter_executions;")
