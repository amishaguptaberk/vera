"""Evidence: records, append-only versions, findings and links, attachments, checks.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"

APPEND_ONLY = ["evidence_versions", "finding_links", "attachments"]
TABLES = [
    "evidence_checks",
    "attachments",
    "finding_links",
    "findings",
    "evidence_versions",
    "evidence_records",
]

DDL = """
create table evidence_records (
    id text primary key,
    case_id text not null references cases(id),
    kind text not null,
    status text not null default 'supporting' check (status in
        ('supporting', 'missing', 'conflicting', 'superseded', 'pending_review', 'not_relevant')),
    created_at timestamptz not null default now()
);
create table evidence_versions (
    id bigserial primary key,
    record_id text not null references evidence_records(id),
    version integer not null check (version >= 1),
    material_version integer not null,
    fields jsonb not null,
    content_hash text not null,
    source text not null,
    created_by text not null,
    created_at timestamptz not null,
    unique (record_id, version)
);
create table attachments (
    id bigserial primary key,
    record_id text not null,
    version integer not null,
    file_name text not null,
    content_type text not null,
    size_bytes bigint not null,
    sha256 text not null,
    uploader text not null,
    created_at timestamptz not null,
    foreign key (record_id, version) references evidence_versions(record_id, version)
);
create table findings (
    id text primary key,
    case_id text not null references cases(id),
    kind text not null,
    statement text not null,
    status text not null check (status in ('open', 'resolved', 'accepted_unresolved')),
    resolved_by text,
    conflict_field text,
    created_by text not null,
    created_at timestamptz not null
);
create table finding_links (
    id bigserial primary key,
    finding_id text not null references findings(id),
    record_id text not null,
    version integer not null,
    field text not null,
    foreign key (record_id, version) references evidence_versions(record_id, version),
    unique (finding_id, record_id, version, field)
);
create table evidence_checks (
    case_id text not null references cases(id),
    key text not null,
    label text not null,
    kinds jsonb not null,
    status text not null default 'current' check (status in ('current', 'stale')),
    stale_reason text,
    stale_at timestamptz,
    primary key (case_id, key)
);
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
