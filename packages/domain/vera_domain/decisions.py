"""Decision packet, decision and reviewer approval: payloads, reducers, command specs (pure)."""

import json
import re
from typing import Any, Literal

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
from vera_domain.specialists import Finding, SpecialistSpec

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


class RetryPacketPayload(Payload):
    mode: Literal["live", "replay"]


class CompletePacketPayload(Payload):
    packet_version: int = Field(ge=1)
    run_id: str = Field(min_length=1, max_length=64)


# ---- Decision Packet Preparer (specialist contract; it recommends, it decides nothing) ----------

PREPARER = "decision_packet_preparer"
PROMPT_VERSION = "v1"


class Cite(BaseModel):
    record_id: str
    version: int
    field: str
    value: Any


class CitedStatement(BaseModel):
    statement: str = Field(min_length=1)
    citations: list[Cite] = Field(min_length=1)


class PacketOutput(BaseModel):
    statements: list[CitedStatement] = Field(min_length=1)
    recommendation: DecisionKind
    reasons: list[CitedStatement] = Field(min_length=1)


class RecordInfo(BaseModel):
    kind: str
    fields: list[str]


class PacketInput(BaseModel):
    """Record ids, field names and status codes only: values are read with read_field."""

    case_id: str
    records: dict[str, RecordInfo]
    open_conflict_fields: list[str] = []
    open_finding_ids: list[str] = []
    missing: list[str] = []
    policy_status: str | None = None
    policy_code: str | None = None
    policy_rules_failed: list[str] = []


def packet_findings(output: BaseModel) -> list[Finding]:
    """Every citation of every statement and reason is one grounding claim."""
    out: list[Finding] = []
    for part in (*getattr(output, "statements", []), *getattr(output, "reasons", [])):
        for c in part.citations:
            out.append(
                Finding(
                    record_id=c.record_id,
                    version=c.version,
                    field=c.field,
                    value=c.value,
                    statement=part.statement,
                )
            )
    return out


PACKET_SYSTEM_PROMPT = (
    "Decision Packet Preparer. You prepare the summary of a card-dispute decision packet for a "
    "finance analyst. You make no eligibility, credit or policy decision, you approve nothing "
    "and you change no case state: you summarize the evidence and RECOMMEND one of the decision "
    "values (credit, dispute, clear, violation, unresolved); the analyst decides and a reviewer "
    "approves. The stored policy status given to you is authoritative; never contradict it. "
    "Read every value you use with the read_field tool; you may read only the records listed. "
    "Every statement and every reason must cite each value it rests on as {record_id, version, "
    "field, value}, with value and version exactly as read_field returned them. Reply with one "
    "JSON object only: {statements: [{statement, citations}], recommendation, reasons: "
    "[{statement, citations}]}."
)


def _packet_messages(inputs: BaseModel) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": PACKET_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(inputs.model_dump(), sort_keys=True)},
    ]


def build_packet_spec(record_ids: frozenset[str]) -> SpecialistSpec:
    return SpecialistSpec(
        name=PREPARER,
        prompt_version=PROMPT_VERSION,
        input_schema=PacketInput,
        output_schema=PacketOutput,
        allowed_record_ids=lambda case_id: record_ids,
        build_messages=_packet_messages,
        findings_of=packet_findings,
    )


class Citation(BaseModel):
    record_id: str
    version: int
    field: str


register_event_types(
    "decision_packet.created",
    "decision_packet.ready",
    "decision_packet.retried",
    "decision.recorded",
    "approval.requested",
    "approval.approved",
    "approval.returned",
    "approval.reminded",
    "approval.reassigned",
)
register_event_summaries(
    {
        "decision_packet.created": "Decision packet requested",
        "decision_packet.ready": "Decision packet ready",
        "decision_packet.retried": "Decision packet preparation retried",
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
            update={"packet_status": "draft", "decision": "none", "approval_status": "none"}
        ),
        reason="Decision packet requested",
        events=[
            EventDraft(
                "decision_packet.created",
                f"Decision packet v{version} is being prepared",
                [ctx.case_id],
                {k: ctx.extra[k] for k in ("packet_version", "snapshot_hash", "policy_version")},
            )
        ],
        result=dict(ctx.extra),
    )


def reduce_complete_packet(f: CaseFacts, p: CompletePacketPayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f.model_copy(update={"packet_status": "ready"}),
        reason="Decision packet ready",
        events=[
            EventDraft(
                "decision_packet.ready",
                f"Decision packet v{p.packet_version} is ready",
                [ctx.case_id],
                dict(ctx.extra),
            )
        ],
        result=dict(ctx.extra),
    )


def reduce_retry_packet(f: CaseFacts, p: RetryPacketPayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f,
        reason="Decision packet preparation retried",
        events=[
            EventDraft(
                "decision_packet.retried",
                f"Decision packet preparation retried ({p.mode})",
                [ctx.case_id],
                dict(ctx.extra),
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
_PACKET = StepSet(include=frozenset({(_DP, CaseStep.PACKET)}))
RETRY_PACKET = CommandSpec(
    "retry_decision_packet",
    frozenset({Role.ANALYST}),
    RetryPacketPayload,
    _PACKET,
    "packet-retry:{case_id}:{packet_version}:{attempt_no}",
    reduce_retry_packet,
    ("decision_packet.retried",),
    "Retry packet preparation",
    "secondary",
)
# Worker-only: stores the validated specialist output on the packet. Never offered to a human.
COMPLETE_PACKET = CommandSpec(
    "complete_decision_packet",
    frozenset({Role.SYSTEM}),
    CompletePacketPayload,
    _PACKET,
    "packet-done:{case_id}:{packet_version}",
    reduce_complete_packet,
    ("decision_packet.ready",),
    "Complete decision packet",
    "ghost",
)
COMMANDS = (
    RETRY_PACKET,
    CREATE_PACKET,
    RECORD_DECISION,
    REQUEST_APPROVAL,
    APPROVE,
    RETURN,
    REMIND,
    REASSIGN,
)

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
