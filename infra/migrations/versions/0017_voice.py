"""Voice verification calls, webhook events (idempotency ledger) and transcript versions.

Revision ID: 0017
Revises: 0012
"""

from alembic import op

revision = "0017"
down_revision = "0012"


def upgrade() -> None:
    op.execute(
        """
        create table voice_calls (
            id bigserial primary key,
            callback_id text not null unique references callbacks(id),
            attempt integer not null,
            provider text not null,
            provider_call_id text not null unique,
            conversation_id text not null,
            masked_number text not null,
            run_id text,
            status text not null check (status in ('queued', 'ringing', 'in_progress',
                'completed', 'failed', 'no_answer', 'busy', 'timed_out')),
            started_at timestamptz not null,
            ended_at timestamptz,
            last_event_at timestamptz
        );
        create table voice_webhook_events (
            id bigserial primary key,
            event_id text not null unique,
            provider text not null,
            provider_call_id text not null,
            kind text not null,
            received_at timestamptz not null,
            raw_digest text not null,
            processed_at timestamptz,
            result text not null
        );
        create table voice_transcript_versions (
            id bigserial primary key,
            callback_id text not null references callbacks(id),
            version integer not null,
            event_id text not null,
            lines jsonb not null,
            answers jsonb not null,
            rejected jsonb not null,
            confidence double precision not null,
            created_at timestamptz not null,
            unique (callback_id, version)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        "drop table voice_transcript_versions; drop table voice_webhook_events; "
        "drop table voice_calls;"
    )
