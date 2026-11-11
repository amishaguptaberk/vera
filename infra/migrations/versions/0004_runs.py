"""Workflow runs, steps, job queue and the LangGraph checkpointer tables.

The checkpointer's own tables are created here with PostgresSaver.setup() (idempotent) and
dropped on downgrade; the worker does not create schema at start.

Revision ID: 0004
Revises: 0002
"""

import os

from alembic import op

revision = "0004"
down_revision = "0005"

DDL = """
create table workflow_runs (
    id text primary key,
    case_id text not null references cases(id),
    workflow_version integer not null,
    policy_version integer not null,
    status text not null default 'running'
        check (status in ('queued', 'running', 'succeeded', 'failed')),
    mode text not null check (mode in ('live', 'replay')),
    created_at timestamptz not null,
    updated_at timestamptz not null
);
create index workflow_runs_case on workflow_runs(case_id);
create table workflow_steps (
    run_id text not null references workflow_runs(id) on delete cascade,
    step_key text not null,
    specialist text not null,
    status text not null check (status in ('queued', 'running', 'succeeded', 'failed')),
    execution_mode text check (execution_mode in ('live', 'replay')),
    model_id text,
    prompt_version text,
    usage jsonb not null default '{}'::jsonb,
    attempts integer not null default 0,
    failure_reason text,
    error text,
    output jsonb,
    tool_calls jsonb not null default '[]'::jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    primary key (run_id, step_key)
);
create table jobs (
    id bigserial primary key,
    kind text not null,
    payload jsonb not null default '{}'::jsonb,
    status text not null default 'queued' check (status in ('queued', 'running', 'done', 'failed')),
    run_after timestamptz not null,
    attempts integer not null default 0,
    locked_by text,
    locked_at timestamptz,
    last_error text,
    created_at timestamptz not null
);
create index jobs_claim on jobs(status, run_after);
"""

CHECKPOINT_TABLES = (
    "checkpoint_writes",
    "checkpoint_blobs",
    "checkpoints",
    "checkpoint_migrations",
)


def _plain_url() -> str:
    url = os.environ.get("VERA_DATABASE_URL", "postgresql://vera:vera@127.0.0.1:54329/vera")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def upgrade() -> None:
    op.execute(DDL)
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(_plain_url()) as saver:
        saver.setup()


def downgrade() -> None:
    op.execute("drop table if exists jobs")
    op.execute("drop table if exists workflow_steps")
    op.execute("drop table if exists workflow_runs")
    for table in CHECKPOINT_TABLES:
        op.execute(f"drop table if exists {table}")
