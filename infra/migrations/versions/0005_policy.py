"""Policy Controller: immutable policy versions and append-only evaluations.

Revision ID: 0005
Revises: 0002
"""

from alembic import op

revision = "0005"
down_revision = "0002"

DDL = """
create table policy_versions (
    policy_id text not null,
    version integer not null,
    rules jsonb not null,
    created_at timestamptz not null default now(),
    primary key (policy_id, version)
);
create table policy_evaluations (
    id bigserial primary key,
    case_id text not null references cases(id),
    policy_version integer not null,
    snapshot_hash text not null,
    status text not null check (status in
        ('eligible', 'needs_evidence', 'blocked', 'ineligible')),
    code text not null,
    result jsonb not null,
    evidence_ids jsonb not null default '[]'::jsonb,
    event_id bigint,
    created_at timestamptz not null
);
create index policy_evaluations_case_idx on policy_evaluations (case_id, id);
"""


def upgrade() -> None:
    op.execute(DDL)
    for table in ("policy_versions", "policy_evaluations"):
        op.execute(
            f"create trigger {table}_append_only before update or delete on {table} "
            "for each row execute function vera_forbid_mutation()"
        )


def downgrade() -> None:
    op.execute("drop table if exists policy_evaluations")
    op.execute("drop table if exists policy_versions")
