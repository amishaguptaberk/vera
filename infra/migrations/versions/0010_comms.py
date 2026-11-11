"""Cardholder follow-up (VER-005): communications, drafts, responses.

communications is mutable (status moves drafted -> sent -> reminded/overdue -> responded);
communication_drafts and communication_responses are append-only records.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute(
        """
        create table communications (
            id text primary key,
            case_id text not null references cases(id),
            kind text not null default 'cardholder_request',
            status text not null check (status in
                ('drafted', 'sent', 'reminded', 'overdue', 'responded')),
            channel text,
            subject text not null,
            body text not null,
            questions jsonb not null,
            attachments jsonb not null default '[]',
            delivery jsonb,
            reminders integer not null default 0,
            review_recommendation jsonb,
            response_review text not null default 'none' check (response_review in
                ('none', 'complete', 'incomplete', 'conflicting')),
            created_by text not null,
            created_at timestamptz not null,
            sent_by text,
            sent_at timestamptz,
            due_at timestamptz,
            overdue_at timestamptz
        );
        create unique index communications_one_per_case on communications (case_id, kind);
        create table communication_drafts (
            id bigserial primary key,
            communication_id text not null references communications(id),
            version integer not null,
            subject text not null,
            body text not null,
            created_by text not null,
            created_at timestamptz not null,
            unique (communication_id, version)
        );
        create table communication_responses (
            id text primary key,
            communication_id text not null unique references communications(id),
            text text not null,
            evidence_record_id text references evidence_records(id),
            submitted_by text not null,
            submitted_at timestamptz not null
        );
        create trigger communication_drafts_append_only before update or delete
            on communication_drafts for each row execute function vera_forbid_mutation();
        create trigger communication_responses_append_only before update or delete
            on communication_responses for each row execute function vera_forbid_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "drop table communication_responses; drop table communication_drafts;"
        " drop table communications;"
    )
