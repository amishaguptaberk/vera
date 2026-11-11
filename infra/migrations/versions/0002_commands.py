"""Command gateway: idempotency keys, hold/opened facts, event detail, user-cardholder link.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"

DDL = """
create table idempotency_keys (
    key text primary key,
    command text not null,
    case_id text not null references cases(id),
    status text not null check (status in
        ('pending', 'completed', 'failed_before_effect', 'checking')),
    request_id text not null,
    request_hash text not null,
    attempts integer not null default 1,
    first_at timestamptz not null,
    last_at timestamptz not null,
    result jsonb,
    event_ids jsonb not null default '[]'::jsonb
);
alter table cases add column opened_at timestamptz;
alter table cases add column hold jsonb;
alter table audit_events add column detail jsonb not null default '{}'::jsonb;
alter table users add column cardholder_id text references cardholders(id);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("drop table if exists idempotency_keys")
    op.execute("alter table users drop column if exists cardholder_id")
    op.execute("alter table audit_events drop column if exists detail")
    op.execute("alter table cases drop column if exists hold")
    op.execute("alter table cases drop column if exists opened_at")
