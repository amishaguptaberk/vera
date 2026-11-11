"""Credit, dispute and card controls.

Rows are mutable (status changes in place); the audit trail is the credit.*, dispute.* and
controls.* events plus adapter_executions.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"


def upgrade() -> None:
    op.execute(
        """
        create table provisional_credits (
            id bigserial primary key,
            case_id text not null unique references cases(id),
            transaction_id text not null unique references card_transactions(id),
            amount_cents bigint not null check (amount_cents > 0),
            currency text not null,
            status text not null
                check (status in ('requested', 'uncertain', 'issued', 'failed')),
            execution_key text not null unique,
            reference text,
            requested_by text not null,
            issued_at timestamptz,
            created_at timestamptz not null,
            updated_at timestamptz not null
        );
        create table dispute_packets (
            id bigserial primary key,
            case_id text not null unique references cases(id),
            status text not null
                check (status in ('prepared', 'opened', 'reviewed', 'submitted', 'failed')),
            submission_reference text,
            submitted_at timestamptz,
            created_by text not null,
            created_at timestamptz not null,
            updated_at timestamptz not null
        );
        create table control_plans (
            id bigserial primary key,
            case_id text not null unique references cases(id),
            status text not null check (status in
                ('recommended', 'proposed', 'skipped', 'approved', 'declined', 'applied')),
            controls jsonb not null,
            reason text,
            proposed_by text,
            decided_by text,
            created_at timestamptz not null,
            updated_at timestamptz not null
        );
        create table card_controls (
            id bigserial primary key,
            case_id text not null references cases(id),
            plan_id bigint not null references control_plans(id),
            control text not null,
            reference text not null,
            applied_by text not null,
            applied_at timestamptz not null,
            unique (plan_id, control)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        "drop table card_controls; drop table control_plans; drop table dispute_packets; "
        "drop table provisional_credits;"
    )
