"""Workflow runs keep their creation order: the demo clock can stamp several runs with the same
instant, so `created_at` alone cannot tell which run is the latest.

Revision ID: 0019
Revises: 0018
"""

from alembic import op

revision = "0019"
down_revision = "0018"


def upgrade() -> None:
    op.execute("alter table workflow_runs add column seq bigint generated always as identity;")
    op.execute("create index ix_workflow_runs_case_seq on workflow_runs (case_id, seq);")


def downgrade() -> None:
    op.execute("drop index ix_workflow_runs_case_seq;")
    op.execute("alter table workflow_runs drop column seq;")
