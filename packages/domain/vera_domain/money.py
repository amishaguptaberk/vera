"""Credit, dispute and card controls (VER-010): payloads, reducers and command specs (pure).

Every reducer mirrors the fact value its effect stored (ctx.extra); nothing here assumes an
adapter succeeded. Commands that dispatch to an adapter declare a `*.requested` event; the
outcome event (credit.issued, dispute.submitted, controls.applied) is emitted by the after-effect
only when the stored execution succeeded.
"""

from typing import Literal

from pydantic import Field

from vera_domain.commands import (
    CommandSpec,
    EventDraft,
    NoPayload,
    Payload,
    ReduceContext,
    Reduction,
    StepSet,
)
from vera_domain.enums import CaseState, CaseStep, Role, register_event_types
from vera_domain.facts import CaseFacts
from vera_domain.labels import register_event_summaries

ControlName = Literal["lock", "replace", "virtual", "block", "monitor"]
SIMULATED = "simulated"


class LookupPayload(Payload):
    idempotency_key: str = Field(min_length=1, max_length=128)


class ProposeControlsPayload(Payload):
    controls: list[ControlName] = Field(min_length=1, max_length=5)


class RecommendControlsPayload(Payload):
    controls: list[ControlName] = Field(min_length=1, max_length=5)
    reason: str = Field(min_length=1, max_length=500)


class ReasonPayload(Payload):
    reason: str = Field(min_length=1, max_length=500)


register_event_types(
    "credit.requested",
    "credit.issued",
    "credit.confirmed",
    "execution.looked_up",
    "dispute.prepared",
    "dispute.opened",
    "dispute.reviewed",
    "dispute.submission_requested",
    "dispute.submitted",
    "controls.recommended",
    "controls.requested",
    "controls.skipped",
    "controls.approved",
    "controls.declined",
    "controls.apply_requested",
    "controls.applied",
)
register_event_summaries(
    {
        "credit.requested": "Temporary credit requested (simulated)",
        "credit.issued": "Temporary credit issued (simulated)",
        "credit.confirmed": "Existing credit result confirmed · nothing re-sent",
        "execution.looked_up": "Existing execution result looked up",
        "dispute.prepared": "Dispute packet prepared",
        "dispute.opened": "Dispute packet opened for review",
        "dispute.reviewed": "Dispute packet reviewed",
        "dispute.submission_requested": "Dispute submission requested (simulated)",
        "dispute.submitted": "Dispute submission recorded (simulated)",
        "controls.recommended": "Card control plan prepared",
        "controls.requested": "Control plan sent to the card administrator",
        "controls.skipped": "No card controls needed",
        "controls.approved": "Card controls approved",
        "controls.declined": "Card controls declined",
        "controls.apply_requested": "Card control application requested (simulated)",
        "controls.applied": "Card controls applied (simulated)",
    }
)


def _reducer(fact: str, event: str, reason: str):  # type: ignore[no-untyped-def]
    """Reducer mirroring the stored fact the effect returned in ctx.extra[fact]."""

    def reduce(f: CaseFacts, p: Payload, ctx: ReduceContext) -> Reduction:
        result = dict(ctx.extra)
        return Reduction(
            facts=f.model_copy(update={fact: result[fact]}),
            reason=reason,
            events=[EventDraft(event, reason, [ctx.case_id], {fact: result[fact]})],
            result=result,
        )

    return reduce


_TRACK_STEPS = (
    CaseStep.CTL_PREP,
    CaseStep.CONTROLS,
    CaseStep.DSP_PREPARE,
    CaseStep.DSP_OPEN,
    CaseStep.DSP_REVIEW,
    CaseStep.DSP_SUBMIT,
    CaseStep.DSP_FAILED,
    CaseStep.WAITCTL,
    CaseStep.CTL_APPLY,
)
# Dispute and controls are parallel tracks (decision D3): the case step shows only the analyst's
# focused step, so track commands are accepted on every track step and each effect checks its
# own track's stored status.
TRACKS = StepSet(
    include=frozenset(
        (state, step)
        for state in (CaseState.CREDIT_ISSUED, CaseState.DISPUTE_PREPARED)
        for step in _TRACK_STEPS
    )
)
ANALYST = frozenset({Role.ANALYST})
CARD_ADMIN = frozenset({Role.CARD_ADMIN})

ISSUE = CommandSpec(
    "issue_provisional_credit",
    ANALYST,
    NoPayload,  # the amount is the transaction's posted amount from the DB, never the payload
    StepSet(include=frozenset({(CaseState.CREDIT_APPROVED, CaseStep.ISSUE)})),
    "credit:{case_id}:{case_version}",
    _reducer("credit_status", "credit.requested", "Temporary credit requested"),
    ("credit.requested",),
    "Issue temporary credit — simulated",
    "primary",
    requires_policy=frozenset({"eligible"}),
    requires_approval=True,
    adapter="credit",
)
_CHECK = StepSet(include=frozenset({(CaseState.CREDIT_APPROVED, CaseStep.CREDIT_CHECK)}))
LOOKUP = CommandSpec(
    "lookup_execution_result",
    ANALYST,
    LookupPayload,
    _CHECK,
    "lookup:{case_id}:{case_version}",
    _reducer("credit_status", "execution.looked_up", "Existing result looked up"),
    ("execution.looked_up",),
    "Look up existing result",
    "primary",
    adapter="credit",
)
RECONCILE = CommandSpec(
    "reconcile_execution_result",
    frozenset({Role.SYSTEM}),
    LookupPayload,
    _CHECK,
    "reconcile:{case_id}:{case_version}",
    _reducer("credit_status", "execution.looked_up", "Existing result looked up"),
    ("execution.looked_up",),
    "Reconcile uncertain result",
    "ghost",
    adapter="credit",
)


def _dispute(name: str, key: str, event: str, label: str) -> CommandSpec:
    return CommandSpec(
        name,
        ANALYST,
        NoPayload,
        TRACKS,
        key + ":{case_id}:{case_version}",
        _reducer("dispute_status", event, label),
        (event,),
        label,
        "primary",
        adapter="dispute" if name == "submit_dispute" else None,
    )


PREPARE = _dispute("prepare_dispute_packet", "dsp", "dispute.prepared", "Prepare dispute packet")
OPEN = _dispute("open_dispute_packet", "dsp-open", "dispute.opened", "Open dispute packet")
REVIEW = _dispute("review_dispute_packet", "dsp-review", "dispute.reviewed", "Mark reviewed")
SUBMIT = _dispute(
    "submit_dispute", "dsp-sub", "dispute.submission_requested", "Record submission — simulated"
)


def _controls(
    name: str,
    roles: frozenset[Role],
    payload: type[Payload],
    key: str,
    event: str,
    label: str,
    steps: StepSet = TRACKS,
) -> CommandSpec:
    return CommandSpec(
        name,
        roles,
        payload,
        steps,
        key + ":{case_id}:{case_version}",
        _reducer("controls_status", event, label),
        (event,),
        label,
        "secondary" if "decline" in name or "skip" in name else "primary",
        adapter="card_controls" if name == "apply_card_controls" else None,
    )


RECOMMEND = _controls(
    "recommend_card_controls",
    frozenset({Role.SPECIALIST}),
    RecommendControlsPayload,
    "ctl-rec",
    "controls.recommended",
    "Control plan prepared",
)
PROPOSE = _controls(
    "propose_card_controls",
    ANALYST,
    ProposeControlsPayload,
    "ctl-req",
    "controls.requested",
    "Send control plan",
)
SKIP = _controls(
    "skip_card_controls",
    ANALYST,
    ReasonPayload,
    "ctl-skip",
    "controls.skipped",
    "No controls needed",
)
APPROVE = _controls(
    "approve_card_controls",
    CARD_ADMIN,
    NoPayload,
    "ctl-approve",
    "controls.approved",
    "Approve controls",
)
DECLINE = _controls(
    "decline_card_controls",
    CARD_ADMIN,
    ReasonPayload,
    "ctl-decline",
    "controls.declined",
    "Decline controls",
)
APPLY = _controls(
    "apply_card_controls",
    CARD_ADMIN,
    NoPayload,
    "ctl-apply",
    "controls.apply_requested",
    "Apply approved controls — simulated",
)

HUMAN = {
    s.name: s
    for s in (ISSUE, LOOKUP, PREPARE, OPEN, REVIEW, SUBMIT, PROPOSE, SKIP, APPROVE, DECLINE, APPLY)
}
SERVICE = {RECONCILE.name: RECONCILE, RECOMMEND.name: RECOMMEND}
