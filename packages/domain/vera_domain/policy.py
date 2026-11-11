"""Policy Controller v1: pure, deterministic eligibility from an evidence snapshot.

Rules are data (id, group, predicate name, params, effect); predicates are coded below and
registered by name. Nothing here reads text: free text from messages, findings or chat has no
field the predicates look at, so it cannot change a result. Imports stdlib, pydantic and
vera_domain only (enforced by a test).

Precedence: ineligible > blocked > needs_evidence > eligible. The result code and label come
from the first failed rule, in rule order, of the winning status.
"""

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["eligible", "needs_evidence", "blocked", "ineligible"]
Outcome = Literal["unknown", "authorized", "unauthorized"]
Verification = Literal["none", "confirmed", "failed"]

PRECEDENCE: tuple[Status, ...] = ("ineligible", "blocked", "needs_evidence")
POLICY_ID = "card-charge-investigation"
# Record statuses that mean the record is not part of the current evidence.
INACTIVE = frozenset({"missing", "superseded", "not_relevant"})


class RecordFact(BaseModel):
    record_id: str
    kind: str
    status: str
    current_version: int = 1
    fields: dict[str, Any] = Field(default_factory=dict)


class ConflictFact(BaseModel):
    finding_id: str = ""
    record_ids: list[str] = Field(default_factory=list)
    field: str = ""
    values: list[Any] = Field(default_factory=list)


class PolicyInput(BaseModel):
    transaction_id: str
    amount_cents: int
    currency: str = "USD"
    outcome: Outcome = "unknown"  # authorization outcome from structured verification
    cardholder_authenticated: bool = False
    duplicates_ruled_out: bool = False
    verification: Verification = "none"
    snapshot_hash: str
    records: list[RecordFact] = Field(default_factory=list)
    open_conflicts: list[ConflictFact] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    # Message/finding/chat text. Carried for audit only; no predicate reads it.
    asserted_text: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    id: str
    group: str
    label: str
    predicate: str
    params: dict[str, Any] = Field(default_factory=dict)
    effect: Literal["ineligible", "blocked", "needs_evidence"]
    code: str
    fail_label: str


class PolicyVersion(BaseModel):
    version: int
    rules: list[Rule]


class PolicyResult(BaseModel):
    status: Status
    code: str
    label: str
    rules_passed: list[str]
    rules_failed: list[str]
    evidence_used: list[str]
    snapshot_hash: str
    policy_version: int


Predicate = Callable[[PolicyInput, dict[str, Any]], bool]
PREDICATES: dict[str, Predicate] = {}


def predicate(name: str) -> Callable[[Predicate], Predicate]:
    def register(fn: Predicate) -> Predicate:
        PREDICATES[name] = fn
        return fn

    return register


def _active(inp: PolicyInput) -> list[RecordFact]:
    return [r for r in inp.records if r.status not in INACTIVE]


@predicate("charge_identified")
def _charge_identified(inp: PolicyInput, params: dict[str, Any]) -> bool:
    return bool(inp.transaction_id) and inp.amount_cents > 0


@predicate("cardholder_authenticated")
def _cardholder_authenticated(inp: PolicyInput, params: dict[str, Any]) -> bool:
    return inp.cardholder_authenticated


@predicate("duplicates_ruled_out")
def _duplicates_ruled_out(inp: PolicyInput, params: dict[str, Any]) -> bool:
    return inp.duplicates_ruled_out


@predicate("not_authorized")
def _not_authorized(inp: PolicyInput, params: dict[str, Any]) -> bool:
    return inp.outcome != "authorized"


@predicate("no_conflicts")
def _no_conflicts(inp: PolicyInput, params: dict[str, Any]) -> bool:
    return not inp.open_conflicts and not any(r.status == "conflicting" for r in inp.records)


@predicate("receipt_above_threshold")
def _receipt_above_threshold(inp: PolicyInput, params: dict[str, Any]) -> bool:
    if inp.amount_cents <= int(params["threshold_cents"]):
        return True
    kinds = set(params["kinds"])
    # Allowlist: a pending, conflicting or superseded receipt is not a present receipt.
    return any(r.kind in kinds and r.status == "supporting" for r in inp.records)


@predicate("no_pending_review")
def _no_pending_review(inp: PolicyInput, params: dict[str, Any]) -> bool:
    return not any(r.status == "pending_review" for r in inp.records)


@predicate("verification_not_failed")
def _verification_not_failed(inp: PolicyInput, params: dict[str, Any]) -> bool:
    return inp.verification != "failed"


@predicate("verification_confirmed")
def _verification_confirmed(inp: PolicyInput, params: dict[str, Any]) -> bool:
    return inp.verification == "confirmed"


def _rule(
    id_: str,
    group: str,
    label: str,
    pred: str,
    effect: Literal["ineligible", "blocked", "needs_evidence"],
    code: str,
    fail_label: str,
    **params: Any,
) -> Rule:
    return Rule(
        id=id_,
        group=group,
        label=label,
        predicate=pred,
        params=params,
        effect=effect,
        code=code,
        fail_label=fail_label,
    )


POLICY_V1 = PolicyVersion(
    version=1,
    rules=[
        _rule(
            "charge_identified",
            "Intake",
            "Charge identified",
            "charge_identified",
            "blocked",
            "CHARGE_NOT_IDENTIFIED",
            "Blocked · charge not identified",
        ),
        _rule(
            "cardholder_authenticated",
            "Intake",
            "Cardholder authenticated",
            "cardholder_authenticated",
            "needs_evidence",
            "CARDHOLDER_NOT_AUTHENTICATED",
            "Needs evidence · cardholder not authenticated",
        ),
        _rule(
            "duplicates_ruled_out",
            "Intake",
            "Duplicates ruled out",
            "duplicates_ruled_out",
            "needs_evidence",
            "DUPLICATE_SEARCH_REQUIRED",
            "Needs evidence · duplicate search not done",
        ),
        _rule(
            "charge_not_authorized",
            "Decision and money",
            "Charge was not authorized",
            "not_authorized",
            "ineligible",
            "CHARGE_AUTHORIZED",
            "Ineligible · the cardholder authorized this charge",
        ),
        _rule(
            "purchase_records_agree",
            "Evidence",
            "Purchase records agree",
            "no_conflicts",
            "blocked",
            "EVIDENCE_CONFLICT",
            "Blocked · evidence conflict",
        ),
        _rule(
            "receipt_required_above_threshold",
            "Evidence",
            "Receipt required above $75",
            "receipt_above_threshold",
            "needs_evidence",
            "RECEIPT_REQUIRED",
            "Needs evidence · receipt required above $75",
            threshold_cents=7500,
            kinds=["receipt"],
        ),
        _rule(
            "no_pending_review",
            "Evidence",
            "Evidence reviewed",
            "no_pending_review",
            "needs_evidence",
            "REVIEW_PENDING",
            "Needs evidence · a record awaits review",
        ),
        _rule(
            "verification_not_failed",
            "Evidence",
            "Verification did not fail",
            "verification_not_failed",
            "blocked",
            "VERIFICATION_FAILED",
            "Blocked · verification failed",
        ),
        _rule(
            "structured_verification",
            "Evidence",
            "Structured callback result recorded",
            "verification_confirmed",
            "needs_evidence",
            "VERIFICATION_REQUIRED",
            "Needs evidence · verification call not completed",
        ),
    ],
)

ELIGIBLE_CODE = "CREDIT_ELIGIBLE"
ELIGIBLE_LABEL = "Eligible for credit · reviewer approval required"


def evaluate(policy: PolicyVersion, inp: PolicyInput) -> PolicyResult:
    passed: list[str] = []
    failed: list[Rule] = []
    for rule in policy.rules:
        if PREDICATES[rule.predicate](inp, rule.params):
            passed.append(rule.id)
        else:
            failed.append(rule)
    status: Status = "eligible"
    code, label = ELIGIBLE_CODE, ELIGIBLE_LABEL
    for effect in PRECEDENCE:
        first = next((r for r in failed if r.effect == effect), None)
        if first is not None:
            status, code, label = effect, first.code, first.fail_label
            break
    used = {r.record_id for r in _active(inp)}
    if inp.transaction_id:
        used.add(inp.transaction_id)
    return PolicyResult(
        status=status,
        code=code,
        label=label,
        rules_passed=passed,
        rules_failed=[r.id for r in failed],
        evidence_used=sorted(used),
        snapshot_hash=inp.snapshot_hash,
        policy_version=policy.version,
    )


def policy_input_from(
    case_facts: dict[str, Any], evidence: Any, fallback_snapshot: str = ""
) -> PolicyInput:
    """Build the input from case facts plus an evidence summary read duck-typed by attribute
    name (snapshot_hash, records, open_conflicts, missing). `evidence` may be None."""
    records = [
        RecordFact(
            record_id=r.record_id,
            kind=r.kind,
            status=r.status,
            current_version=r.current_version,
            fields=dict(getattr(r, "fields", {}) or {}),
        )
        for r in getattr(evidence, "records", [])
    ]
    conflicts = [
        ConflictFact(
            finding_id=c.finding_id,
            record_ids=list(c.record_ids),
            field=c.field,
            values=list(c.values),
        )
        for c in getattr(evidence, "open_conflicts", [])
    ]
    facts = dict(case_facts)
    # Structured callback results (a typed record, never message text) drive verification.
    for rec in sorted(records, key=lambda r: r.record_id):
        if rec.kind == "callback" and rec.status == "supporting":
            result = rec.fields.get("result")
            if result in ("confirmed", "failed"):
                facts.setdefault("verification", result)
            answer = rec.fields.get("authorization_answer")
            if answer in ("authorized", "unauthorized"):
                facts.setdefault("outcome", answer)
    return PolicyInput(
        **facts,
        snapshot_hash=getattr(evidence, "snapshot_hash", None) or fallback_snapshot,
        records=records,
        open_conflicts=conflicts,
        missing=list(getattr(evidence, "missing", [])),
    )
