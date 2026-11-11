"""Investigation specialists: pure definitions, prompts and workflow.

The prompts give the model the permitted record ids, kinds and field NAMES only; every value has
to be read through the `read_field` tool, and every claim must cite {record_id, version, field,
value}. The code never decides what the findings are: it validates grounding and scope.
Related charges are identified by full transaction identity, never by a card suffix.
"""

import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from vera_domain.specialists import Finding, SpecialistSpec

PROMPT_VERSION = "v1"

CHARGE = "charge_investigator"
RELATED = "related_transaction_investigator"
RECEIPT = "receipt_document_reviewer"
SPECIALISTS = (CHARGE, RELATED, RECEIPT)

# Record kinds each specialist may read.
PERMITTED_KINDS: dict[str, frozenset[str]] = {
    CHARGE: frozenset({"charge", "purchase_order", "delivery_record"}),
    RELATED: frozenset({"charge", "related_charge", "cardholder_profile"}),
    RECEIPT: frozenset({"charge", "initial_report", "receipt"}),
}

# Workflow v3 investigation segment, as data.
INVESTIGATION_V3: dict[str, Any] = {
    "id": "investigation-v3",
    "nodes": [
        {"key": CHARGE, "kind": "specialist"},
        {"key": RELATED, "kind": "specialist"},
        {"key": RECEIPT, "kind": "specialist"},
        {"key": "pc1", "kind": "policy_check"},
    ],
    "edges": [
        ["__start__", CHARGE],
        ["__start__", RELATED],
        [CHARGE, RECEIPT],
        [RELATED, RECEIPT],
        [RECEIPT, "pc1"],
        ["pc1", "__end__"],
    ],
}


# ---- input -------------------------------------------------------------------------------------


class PermittedRecord(BaseModel):
    record_id: str
    kind: str
    fields: list[str]  # names only; values are read through read_field


class TransactionIdentity(BaseModel):
    """Full identity of the disputed transaction. Deliberately has no card suffix."""

    transaction_id: str
    merchant: str
    amount_cents: int
    currency: str
    cardholder_id: str
    posted_at: str


class InvestigationInput(BaseModel):
    case_id: str
    transaction: TransactionIdentity
    permitted_records: list[PermittedRecord]
    receipt_threshold_cents: int


# ---- output ------------------------------------------------------------------------------------


class Citation(BaseModel):
    record_id: str
    version: int = Field(ge=1)
    field: str
    value: Any


class DraftFinding(BaseModel):
    kind: Literal["discrepancy", "conflict", "related_charge", "note"]
    statement: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)
    conflict_field: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind == "conflict" and (
            not self.conflict_field or len({c.record_id for c in self.citations}) < 2
        ):
            raise ValueError("a conflict needs conflict_field and citations on two records")
        return self


class _Output(BaseModel):
    findings: list[DraftFinding]


class ChargeOutput(_Output):
    amount_matches_purchase_order: bool
    quantity_matches_delivery: bool


IDENTITY_FIELDS = frozenset({"merchant", "amount_cents", "posted_at", "cardholder_id"})


class RelatedOutput(_Output):
    related_transaction_ids: list[str]
    ruled_out_transaction_ids: list[str] = []

    @model_validator(mode="after")
    def _full_identity(self) -> Self:
        """A related charge is linked on full identity, never on a card suffix alone."""
        for f in self.findings:
            if f.kind != "related_charge":
                continue
            fields = {c.field for c in f.citations}
            if not fields & IDENTITY_FIELDS or "card_last4" in fields:
                raise ValueError(
                    "a related_charge finding must cite identity fields (merchant, amount, "
                    "date, cardholder) and must not rest on card digits"
                )
        return self


class ReceiptOutput(_Output):
    receipt_present: bool
    report_classification: Literal["complete", "incomplete", "conflicting"]


def findings_of(output: BaseModel) -> list[Finding]:
    """Every citation becomes one grounding claim."""
    out: list[Finding] = []
    for f in getattr(output, "findings", []):
        for c in f.citations:
            out.append(
                Finding(
                    record_id=c.record_id,
                    version=c.version,
                    field=c.field,
                    value=c.value,
                    statement=f.statement,
                )
            )
    return out


# ---- prompts -----------------------------------------------------------------------------------

_COMMON_RULES = (
    "Rules: you are one specialist in a card-dispute investigation. You make no eligibility, "
    "credit or policy decision and you change no case state; you only report findings. Read "
    "every value you use with the read_field tool; you may read only the permitted records "
    "listed. Every finding must cite each value it rests on as {record_id, version, field, "
    "value}, with value and version exactly as read_field returned them. Use kind 'conflict' "
    "(with conflict_field and citations on both records) when two source records disagree, "
    "'discrepancy' for a gap or mismatch against the charge, 'related_charge' for another "
    "transaction you judge related, 'note' otherwise. Reply with one JSON object only."
)

_PURPOSE: dict[str, str] = {
    CHARGE: (
        "Charge Investigator. Purpose: compare the disputed charge with the purchase order and "
        "the delivery record. Check the charged amount against the approved amount and the "
        "approved quantity against the received quantity, and report each disagreement."
    ),
    RELATED: (
        "Related-Transaction Investigator. Purpose: decide which other transactions on the case "
        "are related to the disputed charge. Judge relatedness on full transaction identity "
        "(transaction id, merchant, amount, date and cardholder) and source support. Never treat "
        "matching card digits as evidence of relatedness. Rule out a candidate whose identity "
        "fields are not supported by the records."
    ),
    RECEIPT: (
        "Receipt and Document Reviewer. Purpose: check whether a receipt is on file for the "
        "charge, given the receipt threshold, and classify the cardholder's initial report as "
        "complete, incomplete or conflicting. If no receipt record is permitted, the receipt is "
        "missing: cite the charge amount that makes it required."
    ),
}

_OUTPUT: dict[str, type[_Output]] = {
    CHARGE: ChargeOutput,
    RELATED: RelatedOutput,
    RECEIPT: ReceiptOutput,
}


def build_messages(specialist: str, inputs: InvestigationInput) -> list[dict[str, Any]]:
    schema = _OUTPUT[specialist].model_json_schema()
    system = (
        f"{_PURPOSE[specialist]}\n\n{_COMMON_RULES}\n\nOutput JSON schema: {json.dumps(schema)}"
    )
    user = {
        "case_id": inputs.case_id,
        "transaction": inputs.transaction.model_dump(),
        "permitted_records": [r.model_dump() for r in inputs.permitted_records],
        "receipt_threshold_cents": inputs.receipt_threshold_cents,
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, sort_keys=True)},
    ]


def specialist_input(
    specialist: str,
    case_id: str,
    transaction: TransactionIdentity,
    records: Mapping[str, tuple[str, list[str]]],
    receipt_threshold_cents: int,
) -> InvestigationInput:
    """records: record_id -> (kind, field names). Filters to the specialist's permitted kinds."""
    kinds = PERMITTED_KINDS[specialist]
    return InvestigationInput(
        case_id=case_id,
        transaction=transaction,
        permitted_records=[
            PermittedRecord(record_id=rid, kind=kind, fields=sorted(fields))
            for rid, (kind, fields) in sorted(records.items())
            if kind in kinds
        ],
        receipt_threshold_cents=receipt_threshold_cents,
    )


def build_spec(specialist: str, record_kinds: Mapping[str, str]) -> SpecialistSpec:
    """Spec for one specialist; scope = record ids of the permitted kinds (from the register)."""
    allowed = frozenset(r for r, k in record_kinds.items() if k in PERMITTED_KINDS[specialist])

    def messages(inputs: BaseModel) -> list[dict[str, Any]]:
        return build_messages(specialist, InvestigationInput.model_validate(inputs.model_dump()))

    return SpecialistSpec(
        name=specialist,
        prompt_version=PROMPT_VERSION,
        input_schema=InvestigationInput,
        output_schema=_OUTPUT[specialist],
        allowed_tools=frozenset({"read_field"}),
        allowed_record_ids=lambda _case_id: allowed,
        build_messages=messages,
        findings_of=findings_of,
    )
