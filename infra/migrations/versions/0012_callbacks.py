"""Verification callbacks: attempts, transcript lines, notes.

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.execute(
        """
        create table callbacks (
            id text primary key,
            case_id text not null references cases(id),
            attempt integer not null,
            status text not null check (status in ('approved', 'in_progress', 'confirmed',
                'contradicted', 'voicemail', 'no_answer', 'incomplete')),
            target_record_id text not null,
            target_field text not null,
            target_version integer not null,
            questions jsonb not null,
            result jsonb,
            approved_by text not null,
            created_at timestamptz not null,
            updated_at timestamptz not null,
            unique (case_id, attempt)
        );
        create table callback_transcript_lines (
            id bigserial primary key,
            callback_id text not null references callbacks(id),
            seq integer not null,
            speaker text not null,
            text text not null,
            created_at timestamptz not null,
            unique (callback_id, seq)
        );
        create table callback_notes (
            id bigserial primary key,
            callback_id text not null references callbacks(id),
            author text not null,
            text text not null,
            created_at timestamptz not null
        );
        """
    )


def downgrade() -> None:
    op.execute(
        "drop table callback_notes; drop table callback_transcript_lines; drop table callbacks;"
    )
