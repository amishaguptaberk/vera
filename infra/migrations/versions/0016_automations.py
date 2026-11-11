"""Automations: workflow definitions/versions/drafts/check runs, specialist and
policy drafts, and the organization-level command keys and events (audit_events and
idempotency_keys require a case_id, so automations keep their own append-only trail).

workflow_versions, workflow_check_runs and automation_events are append-only
(vera_forbid_mutation from 0001): a published version can never be updated or deleted.

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"

APPEND_ONLY = ("workflow_versions", "workflow_check_runs", "automation_events")


def upgrade() -> None:
    op.execute(
        """
        create table workflow_definitions (
            id text primary key,
            name text not null,
            active_version integer not null,
            created_at timestamptz not null default now()
        );
        create table workflow_versions (
            workflow_id text not null references workflow_definitions(id),
            version integer not null,
            graph jsonb not null,
            graph_hash text not null,
            published_by text not null,
            reason text not null,
            created_at timestamptz not null,
            primary key (workflow_id, version)
        );
        create table workflow_drafts (
            workflow_id text not null references workflow_definitions(id),
            version integer not null,
            from_version integer not null,
            graph jsonb not null,
            revision integer not null default 0,
            created_by text not null,
            created_at timestamptz not null,
            updated_at timestamptz not null,
            primary key (workflow_id, version),
            unique (workflow_id)
        );
        create table workflow_check_runs (
            id bigserial primary key,
            workflow_id text not null,
            draft_version integer not null,
            graph_hash text not null,
            passed boolean not null,
            results jsonb not null,
            created_at timestamptz not null
        );
        create table specialist_definitions (
            id text primary key,
            status text not null check (status in ('draft', 'active')),
            fields jsonb not null,
            revision integer not null default 0,
            created_at timestamptz not null,
            updated_at timestamptz not null
        );
        create table policy_drafts (
            policy_id text not null,
            version integer not null,
            from_version integer not null,
            rules jsonb not null,
            created_at timestamptz not null,
            primary key (policy_id, version)
        );
        create table automation_command_keys (
            key text primary key,
            command text not null,
            status text not null,
            request_id text not null,
            request_hash text not null,
            attempts integer not null default 1,
            first_at timestamptz not null,
            last_at timestamptz not null,
            result jsonb,
            event_ids jsonb not null default '[]'
        );
        create table automation_events (
            id bigserial primary key,
            type text not null,
            at timestamptz not null,
            actor_id text not null,
            actor_role text not null,
            record_ids jsonb not null default '[]',
            summary text not null,
            detail jsonb not null default '{}'
        );
        """
    )
    for table in APPEND_ONLY:
        op.execute(
            f"create trigger {table}_append_only before update or delete on {table} "
            "for each row execute function vera_forbid_mutation()"
        )


def downgrade() -> None:
    op.execute(
        "drop table if exists automation_events, automation_command_keys, policy_drafts, "
        "specialist_definitions, workflow_check_runs, workflow_drafts, workflow_versions, "
        "workflow_definitions"
    )
