"""Baseline: parties, cases, intake and append-only history.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None

TABLES = [
    "audit_events",
    "state_transitions",
    "claims",
    "reports",
    "case_assignments",
    "cases",
    "card_transactions",
    "merchants",
    "cardholders",
    "user_roles",
    "users",
]

APPEND_ONLY = ["audit_events", "reports", "state_transitions", "claims"]

DDL = """
create table users (
    id text primary key,
    name text not null,
    created_at timestamptz not null default now()
);
create table user_roles (
    user_id text not null references users(id),
    role text not null,
    primary key (user_id, role)
);
create table cardholders (
    id text primary key,
    name text not null,
    profile_id text not null,
    phone text not null,
    email text not null,
    contact_verified_at timestamptz,
    created_at timestamptz not null default now()
);
create table merchants (
    id text primary key,
    name text not null unique,
    created_at timestamptz not null default now()
);
create table card_transactions (
    id text primary key,
    merchant_id text not null references merchants(id),
    cardholder_id text not null references cardholders(id),
    amount_cents bigint not null check (amount_cents > 0),
    currency char(3) not null,
    card_last4 char(4) not null,
    posted_at timestamptz not null,
    created_at timestamptz not null default now()
);
create table cases (
    id text primary key,
    transaction_id text not null unique references card_transactions(id),
    state text not null,
    step text not null,
    case_version integer not null default 1,
    owner_id text not null references users(id),
    waiting_on_id text,
    due_at timestamptz,
    workflow_version integer not null,
    policy_version integer not null,
    evidence_snapshot text not null,
    credit_cents bigint not null default 0 check (credit_cents >= 0),
    live boolean not null default true,
    display_label text,
    created_at timestamptz not null default now()
);
create table case_assignments (
    id bigserial primary key,
    case_id text not null references cases(id),
    user_id text not null references users(id),
    assigned_at timestamptz not null
);
create table reports (
    id text primary key,
    case_id text not null references cases(id),
    cardholder_id text not null references cardholders(id),
    statement text not null,
    received_at timestamptz not null,
    created_at timestamptz not null default now()
);
create table claims (
    id text primary key,
    report_id text not null references reports(id),
    case_id text not null references cases(id),
    statement text not null,
    created_at timestamptz not null default now()
);
create table state_transitions (
    id bigserial primary key,
    case_id text not null references cases(id),
    prior_state text,
    prior_step text,
    next_state text not null,
    next_step text not null,
    actor_id text not null,
    actor_role text not null,
    reason text not null,
    case_version integer not null,
    workflow_version integer not null,
    policy_version integer not null,
    evidence_snapshot text not null,
    event_id bigint,
    at timestamptz not null
);
create table audit_events (
    id bigserial primary key,
    type text not null,
    case_id text not null references cases(id),
    case_version integer not null,
    at timestamptz not null,
    actor_id text not null,
    actor_role text not null,
    record_ids jsonb not null default '[]'::jsonb,
    summary text not null
);
create function vera_forbid_mutation() returns trigger language plpgsql as $$
begin
    raise exception 'table % is append-only', tg_table_name using errcode = 'restrict_violation';
end;
$$;
"""


def upgrade() -> None:
    op.execute(DDL)
    for table in APPEND_ONLY:
        op.execute(
            f"create trigger {table}_append_only before update or delete on {table} "
            "for each row execute function vera_forbid_mutation()"
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"drop table if exists {table} cascade")
    op.execute("drop function if exists vera_forbid_mutation()")
