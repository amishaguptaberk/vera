"""Final communication and closure (VER-011): pure types, templates, content policy, reducers.

The final cardholder message is built deterministically from RECORDED facts (no model call) and
every draft, including analyst edits, passes `content_violations`: a sentence that asserts an
action (credit issued, dispute submitted, card controls applied) is allowed only when the
matching fact is recorded.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from vera_domain.commands import EventDraft, NoPayload, Payload, ReduceContext, Reduction
from vera_domain.facts import CaseFacts

ItemStatus = Literal["met", "unmet", "unknown"]


class ChecklistItem(BaseModel):
    name: str
    label: str
    status: ItemStatus
    record_ids: list[str] = Field(default_factory=list)
    detail: str = ""


class ClosureChecklist(BaseModel):
    case_id: str
    ready: bool
    items: list[ChecklistItem]


class UpdateFinalMessagePayload(Payload):
    body: str = Field(min_length=1, max_length=4000)


class CloseCasePayload(Payload):
    reason: str = Field(min_length=5, max_length=500)
    outcome: Literal["resolved", "no_action", "unresolved"]


DraftFinalMessagePayload = NoPayload
SendFinalMessagePayload = NoPayload


# ---- content policy -----------------------------------------------------------------------------

Claim = Literal["credit_issued", "dispute_submitted", "controls_applied"]

_CLAIMS: dict[Claim, re.Pattern[str]] = {
    "credit_issued": re.compile(
        r"\bcredit(ed)?\b.*\b(issued|applied|posted|added)\b|\b(issued|posted|applied)\b.*\bcredit\b"
        r"|\bwe (have )?(credited|refunded)\b",
        re.I,
    ),
    "dispute_submitted": re.compile(
        r"\bdispute\b.*\b(submitted|filed|opened|raised)\b|\b(submitted|filed)\b.*\bdispute\b", re.I
    ),
    "controls_applied": re.compile(
        r"\b(card|controls?)\b.*\b(locked|blocked|frozen|replaced|applied)\b"
        r"|\b(locked|blocked|froze|replaced)\b.*\bcard\b",
        re.I,
    ),
}
_NEGATION = re.compile(r"\b(no|not|never|hasn't|haven't|isn't|wasn't|without)\b|n't\b", re.I)


def recorded_claims(f: CaseFacts) -> set[Claim]:
    allowed: set[Claim] = set()
    if f.credit_status == "issued":
        allowed.add("credit_issued")
    if f.dispute_status == "submitted":
        allowed.add("dispute_submitted")
    if f.controls_status == "applied":
        allowed.add("controls_applied")
    return allowed


def content_violations(body: str, f: CaseFacts) -> list[dict[str, str]]:
    """Each sentence asserting an action that is not recorded -> {claim, sentence}."""
    allowed = recorded_claims(f)
    out: list[dict[str, str]] = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", body):
        if not sentence.strip() or _NEGATION.search(sentence):
            continue
        for claim, pattern in _CLAIMS.items():
            if claim not in allowed and pattern.search(sentence):
                out.append({"claim": claim, "sentence": sentence.strip()})
    return out


def render_final_message(f: CaseFacts, *, cardholder_name: str, case_id: str) -> str:
    """Deterministic template over recorded facts only."""
    lines = [f"Hello {cardholder_name},", "", f"Here is the outcome of your report ({case_id})."]
    if f.credit_status == "issued":
        lines.append("A temporary credit for the charge has been issued to your account.")
    else:
        lines.append("No credit has been issued for this charge.")
    if f.dispute_status == "submitted":
        lines.append("We have submitted a dispute with the merchant on your behalf.")
    else:
        lines.append("No dispute is being pursued for this charge.")
    if f.controls_status == "applied":
        lines.append("The card controls we discussed have been applied to your card.")
    else:
        lines.append("No changes have been made to your card.")
    if f.dispute_status == "submitted":
        lines.append(
            "What to expect: we will write to you again when the dispute outcome is known."
        )
    else:
        lines.append("What to expect: no further action is needed from you.")
    lines += ["", "Thank you,", "Card Services"]
    return "\n".join(lines)


# ---- reducers (mirror the rows the effects wrote) -----------------------------------------------


def reduce_draft(f: CaseFacts, p: NoPayload, ctx: ReduceContext) -> Reduction:
    mid = ctx.extra["message_id"]
    return Reduction(
        facts=f.model_copy(update={"final_message_status": "drafted"}),
        reason="Final update drafted from recorded state",
        events=[EventDraft("final_message.drafted", "Final update drafted", [ctx.case_id, mid])],
        result={"message_id": mid},
    )


def reduce_update(f: CaseFacts, p: UpdateFinalMessagePayload, ctx: ReduceContext) -> Reduction:
    mid = ctx.extra["message_id"]
    return Reduction(
        facts=f.model_copy(update={"final_message_status": "drafted"}),
        reason="Final update edited",
        events=[EventDraft("final_message.updated", "Final update edited", [ctx.case_id, mid])],
        result={"message_id": mid},
    )


def reduce_send(f: CaseFacts, p: NoPayload, ctx: ReduceContext) -> Reduction:
    mid = ctx.extra["message_id"]
    return Reduction(
        facts=f.model_copy(update={"final_message_status": "sent"}),
        reason="Final update sent",
        events=[
            EventDraft(
                "final_message.sent",
                "Final update sent to the cardholder",
                [ctx.case_id, mid],
                {"execution_id": ctx.extra.get("execution_id")},
            )
        ],
        result={"message_id": mid, "sent_at": ctx.now.isoformat()},
    )


def reduce_close(f: CaseFacts, p: CloseCasePayload, ctx: ReduceContext) -> Reduction:
    monitoring = bool(ctx.extra["monitoring"])
    state = "monitoring" if monitoring else "closed"
    return Reduction(
        facts=f.model_copy(update={"monitoring": monitoring, "closed": not monitoring}),
        reason=p.reason,
        events=[
            EventDraft(
                "case.closed",
                "Case closed" if not monitoring else "Case closed · monitoring the dispute",
                [ctx.case_id, ctx.extra["closure_id"]],
                {"reason": p.reason, "outcome": p.outcome, "state": state},
            )
        ],
        result={"closure_id": ctx.extra["closure_id"], "state": state},
    )
