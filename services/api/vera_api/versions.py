"""Versions a NEW case pins at intake: the active published workflow and the latest published
policy. Reads rows only (no automations import), so intake can call it without a cycle. Falls
back to the seeded workflow v3 / policy v1 only when no published row exists."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vera_domain.automations import WORKFLOW_ID
from vera_domain.policy import POLICY_ID

from vera_api.models_automations import WorkflowDefinition
from vera_api.models_policy import PolicyVersionRow

SEEDED_WORKFLOW_VERSION = 3
SEEDED_POLICY_VERSION = 1


def active_versions(session: Session) -> tuple[int, int]:
    """(workflow_version, policy_version) for a case created now."""
    wf = session.get(WorkflowDefinition, WORKFLOW_ID)
    workflow = wf.active_version if wf is not None else SEEDED_WORKFLOW_VERSION
    policy = session.scalar(
        select(func.max(PolicyVersionRow.version)).where(PolicyVersionRow.policy_id == POLICY_ID)
    )
    return workflow, policy if policy is not None else SEEDED_POLICY_VERSION
