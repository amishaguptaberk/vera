"""Decision packet, decision and reviewer approval: payloads, reducers, command specs (pure)."""

import re
from typing import Literal

from pydantic import BaseModel, Field

from vera_domain.commands import (
    CommandSpec,
    EventDraft,
    NoPayload,
    Payload,
    ReduceContext,
    Reduction,
    StepSet,
)
from vera_domain.enums import CaseState, CaseStep, Role, StateKind, register_event_types
from vera_domain.facts import CaseFacts
from vera_domain.labels import register_event_summaries, register_labels

DecisionKind = Literal["credit", "dispute", "clear", "violation", "unresolved"]

# Policy statuses that allow each decision (Handoff 7.4): credit only on an eligible evaluation;
# the other decisions never grant credit, so any stored evaluation allows them.
ANY_POLICY = frozenset({"eligible", "needs_evidence", "blocked", "ineligible"})
DECISION_POLICY: dict[str, frozenset[str]] = {
    "credit": frozenset({"eligible"}),
    "dispute": ANY_POLICY,
    "clear": ANY_POLICY,
    "violation": ANY_POLICY,
    "unresolved": ANY_POLICY,
}


class RecordDecisionPayload(Payload):
    decision: DecisionKind
    rationale: str = Field(min_length=1)


class ReturnDecisionPayload(Payload):
    reason: str = Field(min_length=1)
    next_step: str = Field(min_length=1)
    owner: str = Field(min_length=1)


class ReassignReviewerPayload(Payload):
    to: str = Field(min_length=1)


class Citation(BaseModel):
    record_id: str
    version: int
    field: str


register_event_types(
    "decision_packet.created",
    "decision.recorded",
    "approval.requested",
    "approval.approved",
    "approval.returned",
    "approval.reminded",
    "approval.reassigned",
)
register_event_summaries(
    {
        "decision_packet.created": "Decision packet prepared",
        "decision.recorded": "Decision recorded",
        "approval.requested": "Reviewer approval requested",
        "approval.approved": "Decision approved by the reviewer",
        "approval.returned": "Decision returned by the reviewer",
        "approval.reminded": "Reviewer reminded",
        "approval.reassigned": "Reviewer reassigned",
    }
)
register_labels(
    {
        (CaseState.DECISION_PENDING, CaseStep.PACKET): (
            "Decision pending",
            StateKind.REVIEW,
            "Prepare decision packet",
        ),
        (CaseState.DECISION_PENDING, CaseStep.DECIDE): (
            "Decision pending",
            StateKind.REVIEW,
            "Record decision",
        ),
        (CaseState.REVIEWER_PENDING, CaseStep.WAITRV): (
            "Waiting on reviewer",
            StateKind.WAITING,
            "Remind or reassign reviewer",
        ),
        (CaseState.DECISION_PENDING, CaseStep.RETURNED): (
            "Returned by reviewer",
            StateKind.BLOCKED,
            "Prepare a new packet version",
        ),
        (CaseState.DECISION_PENDING, CaseStep.STALE): (
            "Approval out of date",
            StateKind.BLOCKED,
            "Prepare a new packet version",
        ),
    }
)


def reduce_create_packet(f: CaseFacts, p: NoPayload, ctx: ReduceContext) -> Reduction:
    version = ctx.extra["packet_version"]
    return Reduction(
        facts=f.model_copy(
            update={"packet_status": "ready", "decision": "none", "approval_status": "none"}
        ),
        reason="Decision packet prepared",
        events=[
            EventDraft(
                "decision_packet.created",
                f"Decision packet v{version} prepared",
                [ctx.case_id],
                {k: ctx.extra[k] for k in ("packet_version", "snapshot_hash", "policy_version")},
            )
        ],
        result=dict(ctx.extra),
    )


def reduce_record_decision(f: CaseFacts, p: RecordDecisionPayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f.model_copy(update={"decision": p.decision}),
        reason="Decision recorded",
        events=[
            EventDraft(
                "decision.recorded",
                f"Decision recorded: {p.decision}",
                [ctx.case_id],
                {"decision": p.decision, "packet_version": ctx.extra["packet_version"]},
            )
        ],
        result=dict(ctx.extra),
    )


def _approval(status: str | None, event: str, reason: str) -> object:
    def reducer(f: CaseFacts, p: Payload, ctx: ReduceContext) -> Reduction:
        facts = f if status is None else f.model_copy(update={"approval_status": status})
        return Reduction(
            facts=facts,
            reason=reason,
            events=[EventDraft(event, reason, [ctx.extra["approval_id"]], dict(ctx.extra))],
            result=dict(ctx.extra),
        )

    return reducer


_DP = CaseState.DECISION_PENDING
_DECIDE = StepSet(include=frozenset({(_DP, CaseStep.DECIDE)}))
_WAITRV = StepSet(include=frozenset({(CaseState.REVIEWER_PENDING, CaseStep.WAITRV)}))

CREATE_PACKET = CommandSpec(
    "create_decision_packet",
    frozenset({Role.ANALYST}),
    NoPayload,
    StepSet(
        include=frozenset(
            {
                (_DP, s)
                for s in (CaseStep.PACKET, CaseStep.DECIDE, CaseStep.RETURNED, CaseStep.STALE)
            }
        )
    ),
    "packet:{case_id}:{case_version}",
    reduce_create_packet,
    ("decision_packet.created",),
    "Prepare decision packet",
    "primary",
)
RECORD_DECISION = CommandSpec(
    "record_decision",
    frozenset({Role.ANALYST}),
    RecordDecisionPayload,
    _DECIDE,
    "decision:{case_id}:{case_version}",
    reduce_record_decision,
    ("decision.recorded",),
    "Record decision",
    "primary",
    requires_policy=ANY_POLICY,
)
REQUEST_APPROVAL = CommandSpec(
    "request_reviewer_approval",
    frozenset({Role.ANALYST}),
    NoPayload,
    _DECIDE,
    "approval-request:{case_id}:{packet_version}",
    _approval("requested", "approval.requested", "Reviewer approval requested"),  # type: ignore[arg-type]
    ("approval.requested",),
    "Send to reviewer",
    "primary",
    requires_policy=frozenset({"eligible"}),
)
APPROVE = CommandSpec(
    "approve_decision",
    frozenset({Role.REVIEWER}),
    NoPayload,
    # Also reachable in `stale` so an out-of-date approval answers 422 approval_stale.
    StepSet(
        include=frozenset({(CaseState.REVIEWER_PENDING, CaseStep.WAITRV), (_DP, CaseStep.STALE)})
    ),
    "approve:{case_id}:{approval_id}",
    _approval("approved", "approval.approved", "Decision approved"),  # type: ignore[arg-type]
    ("approval.approved",),
    "Approve decision",
    "primary",
)
RETURN = CommandSpec(
    "return_decision",
    frozenset({Role.REVIEWER}),
    ReturnDecisionPayload,
    _WAITRV,
    "return:{case_id}:{approval_id}",
    _approval("returned", "approval.returned", "Decision returned to the analyst"),  # type: ignore[arg-type]
    ("approval.returned",),
    "Return to analyst",
    "secondary",
)
REMIND = CommandSpec(
    "remind_reviewer",
    frozenset({Role.ANALYST}),
    NoPayload,
    _WAITRV,
    "remind-reviewer:{case_id}:{case_version}",
    _approval(None, "approval.reminded", "Reviewer reminded"),  # type: ignore[arg-type]
    ("approval.reminded",),
    "Remind reviewer",
    "secondary",
)
REASSIGN = CommandSpec(
    "reassign_reviewer",
    frozenset({Role.ANALYST, Role.OPS_ADMIN}),
    ReassignReviewerPayload,
    _WAITRV,
    "reassign-reviewer:{case_id}:{case_version}",
    _approval(None, "approval.reassigned", "Reviewer reassigned"),  # type: ignore[arg-type]
    ("approval.reassigned",),
    "Reassign reviewer",
    "ghost",
)
COMMANDS = (CREATE_PACKET, RECORD_DECISION, REQUEST_APPROVAL, APPROVE, RETURN, REMIND, REASSIGN)

# ---- Ask Vera: deterministic intents (Handoff 3.4), explicit before generic ---------------------

REFUSAL = "Approval must be recorded with the reviewer action below, not through chat."
UNKNOWN = "I can answer questions about this case's evidence, policy and approval status."
_INTENTS: tuple[tuple[str, str], ...] = (
    ("approve", r"\bapprov(e|al)\b.*\b(it|this|that|packet|decision|credit|for me)\b|^approve\b"),
    ("issue_credit", r"\bissue\b.*\bcredit\b"),
    ("credit_blocked", r"\bcredit\b.*\b(blocked|block)\b|\bwhy\b.*\bcredit\b"),
    ("stale", r"\b(stale|out of date)\b"),
    ("policy", r"\bpolicy\b"),
)


def ask_intent(text: str) -> str:
    q = re.sub(r"\s+", " ", text.strip().lower())
    for intent, pattern in _INTENTS:
        if re.search(pattern, q):
            return intent
    return "unknown"
