"""Dispute Packet Preparer specialist: the dispute reason code and a cited narrative.

The prompt carries record ids, kinds and field NAMES only; every value is read with `read_field`
from the evidence register, the open findings, the response review and the callback result (if
present). Each statement cites one {record_id, version, field, value}. The code validates the
grounding; it never chooses the reason code or writes the text. The narrative never gates the
dispute track: the analyst opens, reviews and submits the packet whether it is ready or not.
"""

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from vera_domain.commands import CommandSpec, EventDraft, Payload, ReduceContext, Reduction, StepSet
from vera_domain.enums import CaseState, Role, register_event_types
from vera_domain.facts import CaseFacts
from vera_domain.investigation import PermittedRecord
from vera_domain.labels import register_event_summaries
from vera_domain.money import TRACKS
from vera_domain.specialists import Finding, SpecialistSpec

PREPARER = "dispute_packet_preparer"
PROMPT_VERSION = "v1"
REASON_CODES = (
    "unauthorized",
    "goods_not_received",
    "quantity_mismatch",
    "amount_mismatch",
    "duplicate",
)
ReasonCode = Literal[
    "unauthorized", "goods_not_received", "quantity_mismatch", "amount_mismatch", "duplicate"
]
# Register kinds the preparer may read (never the cardholder profile), plus the two read-only
# views the service exposes as records: open findings and the cardholder response review.
EVIDENCE_KINDS = frozenset(
    {
        "charge",
        "purchase_order",
        "delivery_record",
        "initial_report",
        "receipt",
        "related_charge",
        "callback",
    }
)
FINDING_KIND = "finding"
FINDING_FIELDS = ("kind", "statement")
REVIEW_KIND = "response_review"
REVIEW_FIELDS = ("outcome",)
PERMITTED_KINDS = EVIDENCE_KINDS | {FINDING_KIND, REVIEW_KIND}


class PreparerInput(BaseModel):
    case_id: str
    permitted_records: list[PermittedRecord]
    reason_codes: list[str]


class Statement(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    record_id: str
    version: int = Field(ge=1)
    field: str
    value: Any


class PreparerOutput(BaseModel):
    reason_code: ReasonCode
    statements: list[Statement] = Field(min_length=1, max_length=5)


def findings_of(output: BaseModel) -> list[Finding]:
    """Every statement is one grounding claim."""
    return [
        Finding(
            record_id=s.record_id,
            version=s.version,
            field=s.field,
            value=s.value,
            statement=s.text,
        )
        for s in getattr(output, "statements", [])
    ]


_SYSTEM = (
    "Dispute Packet Preparer. Purpose: prepare the reason code and a short cited narrative for a "
    "card-network dispute packet that a finance analyst opens, reviews and submits. You submit "
    "nothing and change no case state. Choose reason_code from: unauthorized, "
    "goods_not_received, quantity_mismatch, amount_mismatch, duplicate. Read every value you use "
    "with the read_field tool, only from the permitted records (evidence register, open "
    "findings, response review, callback result). Write 1 to 5 statements; each statement cites "
    "exactly one value as record_id, version, field and value, exactly as read_field returned "
    "them. Reply with one JSON object only."
)


def build_messages(inputs: PreparerInput) -> list[dict[str, Any]]:
    schema = PreparerOutput.model_json_schema()
    return [
        {"role": "system", "content": f"{_SYSTEM}\n\nOutput JSON schema: {json.dumps(schema)}"},
        {"role": "user", "content": json.dumps(inputs.model_dump(), sort_keys=True)},
    ]


def preparer_input(case_id: str, records: Mapping[str, tuple[str, list[str]]]) -> PreparerInput:
    """`records`: record id -> (kind, field names), register records and service views alike."""
    return PreparerInput(
        case_id=case_id,
        permitted_records=[
            PermittedRecord(record_id=rid, kind=kind, fields=sorted(fields))
            for rid, (kind, fields) in sorted(records.items())
            if kind in PERMITTED_KINDS
        ],
        reason_codes=list(REASON_CODES),
    )


def build_spec(record_kinds: Mapping[str, str]) -> SpecialistSpec:
    allowed = frozenset(r for r, k in record_kinds.items() if k in PERMITTED_KINDS)

    def messages(inputs: BaseModel) -> list[dict[str, Any]]:
        return build_messages(PreparerInput.model_validate(inputs.model_dump()))

    return SpecialistSpec(
        name=PREPARER,
        prompt_version=PROMPT_VERSION,
        input_schema=PreparerInput,
        output_schema=PreparerOutput,
        allowed_tools=frozenset({"read_field"}),
        allowed_record_ids=lambda _case_id: allowed,
        build_messages=messages,
        findings_of=findings_of,
    )


# ---- commands -----------------------------------------------------------------------------------


class RecordNarrativePayload(Payload):
    """Names the packet and the run whose VALIDATED step output is stored (never caller text)."""

    packet_id: int = Field(ge=1)
    run_id: str = Field(min_length=1, max_length=64)


class RetryNarrativePayload(Payload):
    mode: Literal["live", "replay"]


register_event_types("dispute.narrative_recorded", "dispute.narrative_retried")
register_event_summaries(
    {
        "dispute.narrative_recorded": "Dispute reason code and narrative prepared",
        "dispute.narrative_retried": "Dispute narrative preparation retried",
    }
)


def _reduce(event: str, reason: str):  # type: ignore[no-untyped-def]
    """No case fact changes: the narrative lives on the packet and never gates the track."""

    def reduce(f: CaseFacts, p: Payload, ctx: ReduceContext) -> Reduction:
        result = dict(ctx.extra)
        return Reduction(
            facts=f,
            reason=reason,
            events=[EventDraft(event, reason, [ctx.case_id], result)],
            result=result,
        )

    return reduce


# Stored whenever the specialist finishes, wherever the case is by then (closed cases refuse).
RECORD = CommandSpec(
    "record_dispute_narrative",
    frozenset({Role.SPECIALIST}),
    RecordNarrativePayload,
    StepSet(exclude_states=frozenset({CaseState.CLOSED})),
    "dspnarr:{case_id}:{packet_id}",
    _reduce("dispute.narrative_recorded", "Dispute narrative prepared"),
    ("dispute.narrative_recorded",),
    "Record dispute narrative",
    "ghost",
)
RETRY = CommandSpec(
    "retry_dispute_narrative",
    frozenset({Role.ANALYST}),
    RetryNarrativePayload,
    TRACKS,
    "dspnarr-retry:{case_id}:{case_version}",
    _reduce("dispute.narrative_retried", "Dispute narrative preparation retried"),
    ("dispute.narrative_retried",),
    "Retry dispute narrative",
    "secondary",
)
HUMAN = {RETRY.name: RETRY}
SERVICE = {RECORD.name: RECORD}
