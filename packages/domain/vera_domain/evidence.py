"""Evidence domain: statuses, record kinds, material fields, snapshot hash, service commands.

Service commands (link_evidence, record_claim, record_finding, append_evidence_version) live in
SERVICE_REGISTRY, not REGISTRY: they are never offered to a human role and never listed in
available_actions. The gateway resolves a command from either registry and runs the same gates.
"""

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from vera_domain.commands import (
    CommandSpec,
    EventDraft,
    Payload,
    ReduceContext,
    Reduction,
    ReportId,
    StepSet,
)
from vera_domain.enums import EventType, Role
from vera_domain.facts import CaseFacts

RECEIPT_THRESHOLD_CENTS = 7500  # policy v1: receipt required above $75


class EvidenceStatus(StrEnum):
    SUPPORTING = "supporting"
    MISSING = "missing"
    CONFLICTING = "conflicting"
    SUPERSEDED = "superseded"
    PENDING_REVIEW = "pending_review"
    NOT_RELEVANT = "not_relevant"


class FindingStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ACCEPTED_UNRESOLVED = "accepted_unresolved"
    STALE = "stale"  # a cited version was superseded by a material change


class RecordKind(StrEnum):
    CHARGE = "charge"
    PURCHASE_ORDER = "purchase_order"
    DELIVERY_RECORD = "delivery_record"
    RECEIPT = "receipt"
    INITIAL_REPORT = "initial_report"
    CARDHOLDER_PROFILE = "cardholder_profile"
    RELATED_CHARGE = "related_charge"
    CALLBACK = "callback"  # structured verification result read by the Policy Controller


# Kinds a case must hold before evidence is sufficient; a kind with no record is "missing".
REQUIRED_KINDS = (
    RecordKind.CHARGE,
    RecordKind.PURCHASE_ORDER,
    RecordKind.DELIVERY_RECORD,
    RecordKind.RECEIPT,
    RecordKind.INITIAL_REPORT,
)

# ToSpec 7.4: fields whose change is material, per kind.
MATERIAL_FIELDS: dict[str, tuple[str, ...]] = {
    "charge": ("amount_cents", "merchant", "card_last4", "cardholder_id"),
    "purchase_order": ("approved_quantity", "approved_amount_cents", "merchant"),
    "delivery_record": ("received_quantity",),
    "receipt": ("amount_cents", "version_label"),
    "initial_report": ("statement",),
    "cardholder_profile": ("phone", "verification_target"),
    "related_charge": ("amount_cents", "merchant"),
    "callback": ("result", "authorization_answer"),  # facts used by a policy rule
}

# plan s10: rule -> evidence kinds map. (key, label, kinds)
CHECKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("purchase_records", "Purchase records agree", ("purchase_order", "delivery_record", "charge")),
    ("receipt_required", "Receipt required above $75", ("receipt", "charge")),
    ("identity", "Cardholder identity", ("cardholder_profile",)),
    ("related_charges", "Related charges ruled out", ("related_charge", "charge")),
    ("claim_review", "Claim reviewed", ("initial_report",)),
)


def material_content(kind: str, fields: dict[str, Any]) -> dict[str, Any]:
    names = MATERIAL_FIELDS.get(kind)
    if names is None:
        return dict(fields)
    return {n: fields.get(n) for n in names}


def content_hash(kind: str, fields: dict[str, Any]) -> str:
    """Hash of the material fields only, so a non-material edit keeps the same hash."""
    body = json.dumps(material_content(kind, fields), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def compute_snapshot_hash(
    evidence_versions: list[tuple[str, int, str]], policy_material: dict[str, Any]
) -> str:
    """Pure, deterministic, order-independent sha256 hex over current versions and policy fields."""
    body = json.dumps(
        {"evidence": sorted([r, v, h] for r, v, h in evidence_versions), "policy": policy_material},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


class ConflictValue(BaseModel):
    record_id: str
    version: int
    value: Any


class RecordSummary(BaseModel):
    record_id: str
    kind: str
    status: EvidenceStatus
    current_version: int
    fields: dict[str, Any]


class OpenConflict(BaseModel):
    finding_id: str
    record_ids: list[str]
    field: str
    values: list[ConflictValue]


class EvidenceSummary(BaseModel):
    snapshot_hash: str
    records: list[RecordSummary]
    open_conflicts: list[OpenConflict]
    missing: list[str]


# ---- service commands -------------------------------------------------------------------------

Ident = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class FieldRef(Payload):
    record_id: Ident
    version: int = Field(ge=1)
    field: Ident


class LinkEvidencePayload(Payload):
    finding_id: Ident
    record_id: Ident
    version: int = Field(ge=1)
    field: Ident


class RecordClaimPayload(Payload):
    claim_id: Ident
    report_id: ReportId
    statement: str = Field(min_length=1)


class RecordFindingPayload(Payload):
    finding_id: Ident
    kind: Literal["discrepancy", "conflict", "related_charge", "note"]
    statement: str = Field(min_length=1)
    links: list[FieldRef] = Field(min_length=1)
    status: FindingStatus = FindingStatus.OPEN
    resolved_by: str | None = None
    conflict_field: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind == "conflict" and (not self.conflict_field or len(self.links) < 2):
            raise ValueError("a conflict needs conflict_field and at least two links")
        if self.status == FindingStatus.STALE:
            raise ValueError("stale is set by a material change, not recorded")
        if self.status == FindingStatus.RESOLVED and not self.resolved_by:
            raise ValueError("a resolved finding needs resolved_by")
        return self


class AttachmentIn(Payload):
    file_name: Ident
    content_type: Ident
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AppendVersionPayload(Payload):
    record_id: Ident
    fields: dict[str, Any] = Field(min_length=1)
    source: Ident
    attachment: AttachmentIn | None = None


def _reduce_link(f: CaseFacts, p: LinkEvidencePayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f,
        reason="Evidence linked to finding",
        events=[
            EventDraft(
                EventType.EVIDENCE_LINKED,
                f"{p.record_id} v{p.version} · {p.field} linked to {p.finding_id}",
                [p.finding_id, p.record_id],
                {"version": p.version, "field": p.field},
            )
        ],
        result={"finding_id": p.finding_id, "record_id": p.record_id, "version": p.version},
    )


def _reduce_claim(f: CaseFacts, p: RecordClaimPayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f,
        reason="Claim recorded (not a fact)",
        events=[
            EventDraft(
                EventType.CLAIM_RECORDED,
                f"Claim {p.claim_id} recorded from {p.report_id}",
                [p.claim_id, p.report_id],
            )
        ],
        result={"claim_id": p.claim_id},
    )


def _reduce_finding(f: CaseFacts, p: RecordFindingPayload, ctx: ReduceContext) -> Reduction:
    return Reduction(
        facts=f,
        reason="Finding recorded",
        events=[
            EventDraft(
                EventType.FINDING_RECORDED,
                f"Finding {p.finding_id} recorded ({p.kind}, {p.status.value})",
                [p.finding_id, *dict.fromkeys(link.record_id for link in p.links)],
                {"kind": p.kind, "status": p.status.value},
            )
        ],
        result={"finding_id": p.finding_id, "status": p.status.value},
    )


def _reduce_version(f: CaseFacts, p: AppendVersionPayload, ctx: ReduceContext) -> Reduction:
    result: dict[str, Any] = ctx.extra["result"]
    return Reduction(
        facts=f,
        reason="Evidence version added",
        events=[
            EventDraft(
                EventType.EVIDENCE_VERSION_ADDED,
                f"{p.record_id} v{result['version']} added"
                + (" · material change" if result["material"] else ""),
                [p.record_id],
                result,
            )
        ],
        result=result,
    )


_SERVICE = frozenset({Role.SYSTEM, Role.SPECIALIST})
_ANY = StepSet()

SERVICE_REGISTRY: dict[str, CommandSpec] = {
    s.name: s
    for s in (
        CommandSpec(
            "link_evidence",
            _SERVICE,
            LinkEvidencePayload,
            _ANY,
            "evlink:{finding_id}:{record_id}:{version}:{field}",
            _reduce_link,
            (EventType.EVIDENCE_LINKED,),
            "Link evidence",
            "ghost",
        ),
        CommandSpec(
            "record_claim",
            _SERVICE,
            RecordClaimPayload,
            _ANY,
            "claim:{claim_id}",
            _reduce_claim,
            (EventType.CLAIM_RECORDED,),
            "Record claim",
            "ghost",
        ),
        CommandSpec(
            "record_finding",
            _SERVICE,
            RecordFindingPayload,
            _ANY,
            "finding:{finding_id}",
            _reduce_finding,
            (EventType.FINDING_RECORDED,),
            "Record finding",
            "ghost",
        ),
        # Source-system feed only: a specialist is rejected (fixture 19).
        CommandSpec(
            "append_evidence_version",
            frozenset({Role.SYSTEM}),
            AppendVersionPayload,
            _ANY,
            "evver:{case_id}:{record_id}:{case_version}",
            _reduce_version,
            (EventType.EVIDENCE_VERSION_ADDED,),
            "Add evidence version",
            "ghost",
        ),
    )
}
