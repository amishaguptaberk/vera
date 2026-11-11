"""Decision packets (immutable, versioned), decisions, approvals and Ask Vera pairs.

decision_packets and decisions are append-only (trigger from 0001). approvals change status in
place (requested -> approved | returned | stale); ask_pairs is replaced per question, not audited.

Revision ID: 0013
Revises: 0009
"""

from alembic import op

revision = "0013"
down_revision = "0009"


def upgrade() -> None:
    op.execute(
        """
        create table decision_packets (
            id bigserial primary key,
            case_id text not null references cases(id),
            version integer not null,
            snapshot_hash text not null,
            workflow_version integer not null,
            policy_version integer not null,
            policy_evaluation_id bigint,
            summary jsonb not null,
            run_id text not null,
            created_by text not null,
            created_at timestamptz not null,
            unique (case_id, version)
        );
        create table decision_packet_contents (
            id bigserial primary key,
            case_id text not null references cases(id),
            packet_version integer not null,
            run_id text not null,
            execution_mode text,
            model_id text,
            statements jsonb not null,
            recommendation text not null,
            reasons jsonb not null,
            created_at timestamptz not null,
            unique (case_id, packet_version)
        );
        create table decisions (
            id bigserial primary key,
            case_id text not null references cases(id),
            packet_version integer not null,
            decision text not null
                check (decision in ('credit', 'dispute', 'clear', 'violation', 'unresolved')),
            rationale text not null,
            decided_by text not null,
            decided_at timestamptz not null
        );
        create table approvals (
            id text primary key,
            case_id text not null references cases(id),
            transaction_id text not null,
            packet_version integer not null,
            snapshot_hash text not null,
            policy_version integer not null,
            workflow_version integer not null,
            status text not null
                check (status in ('requested', 'approved', 'returned', 'stale')),
            reviewer_id text not null,
            requested_by text not null,
            requested_at timestamptz not null,
            decided_by text,
            decided_at timestamptz,
            return_reason text,
            return_next_step text,
            return_owner_id text,
            consumed_at timestamptz,
            consumed_execution_id text,
            unique (case_id, packet_version)
        );
        create table ask_pairs (
            id bigserial primary key,
            case_id text not null references cases(id),
            user_id text not null,
            intent text not null,
            signature text not null,
            question text not null,
            answer jsonb not null,
            asked_at timestamptz not null,
            unique (case_id, user_id, intent, signature)
        );
        create trigger decision_packets_append_only before update or delete on decision_packets
            for each row execute function vera_forbid_mutation();
        create trigger decision_packet_contents_append_only before update or delete
            on decision_packet_contents for each row execute function vera_forbid_mutation();
        create trigger decisions_append_only before update or delete on decisions
            for each row execute function vera_forbid_mutation();
        """
    )


def downgrade() -> None:
    op.execute(
        "drop table ask_pairs; drop table approvals; drop table decisions; "
        "drop table decision_packet_contents; "
        "drop table decision_packets;"
    )
