"""Identity verification (VER-006): requests, attempts and the cardholder-only outbox.

The raw one-time code is never stored in identity_verifications or verification_attempts: only a
salted HMAC. verification_outbox holds the simulated delivery to the cardholder (synthetic demo)
and its row is deleted when the request is verified, expired, cancelled or locked.

Revision ID: 0011
Revises: 0009
"""

from alembic import op

revision = "0011"
down_revision = "0009"


def upgrade() -> None:
    op.execute(
        """
        create table identity_verifications (
            id text primary key,
            case_id text not null references cases(id),
            cardholder_id text not null references cardholders(id),
            channel text not null check (channel in ('otp', 'push')),
            status text not null check (status in
                ('requested', 'verified', 'failed', 'expired', 'declined', 'cancelled')),
            code_salt text,
            code_hash text,
            delivery_ref text,
            attempts integer not null default 0,
            max_attempts integer not null,
            sends integer not null default 1,
            requested_by text not null,
            sent_at timestamptz not null,
            last_sent_at timestamptz not null,
            expires_at timestamptz not null,
            resolved_at timestamptz,
            created_at timestamptz not null
        );
        create index identity_verifications_case on identity_verifications (case_id);
        create table verification_attempts (
            id bigserial primary key,
            verification_id text not null references identity_verifications(id),
            attempt_no integer not null,
            outcome text not null check (outcome in ('accepted', 'rejected', 'approved', 'denied')),
            actor_id text not null,
            created_at timestamptz not null,
            unique (verification_id, attempt_no)
        );
        create table verification_outbox (
            id bigserial primary key,
            verification_id text not null unique references identity_verifications(id),
            channel text not null,
            code text,
            created_at timestamptz not null
        );
        """
    )


def downgrade() -> None:
    op.execute(
        "drop table verification_outbox; drop table verification_attempts; "
        "drop table identity_verifications;"
    )
