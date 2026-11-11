"""Evidence service: register reads, snapshot recompute, command side effects, routes, seed."""

import uuid
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vera_domain.clock import Clock
from vera_domain.commands import check_role, resolve_key
from vera_domain.enums import EventType, Role
from vera_domain.errors import CommandError
from vera_domain.evidence import (
    CHECKS,
    RECEIPT_THRESHOLD_CENTS,
    REQUIRED_KINDS,
    SERVICE_REGISTRY,
    ConflictValue,
    EvidenceStatus,
    EvidenceSummary,
    FindingStatus,
    OpenConflict,
    RecordSummary,
    compute_snapshot_hash,
    content_hash,
)

from vera_api import auth, gateway
from vera_api import policy as policy_service
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.config import Settings
from vera_api.intake import _emit
from vera_api.models import CardTransaction, Case, Claim, Report

if TYPE_CHECKING:
    from vera_api.gateway import EffectContext, Outcome
from vera_api.models_evidence import (
    Attachment,
    EvidenceCheck,
    EvidenceRecord,
    EvidenceVersion,
    Finding,
    FindingLink,
)

SNAPSHOT_PREFIX = "sha256:"
SEED_CASE = "CHG-1042"
# The service principal that applies review outcomes (an analyst's response review, a related
# charge decision) to the register. The analyst's own command carries the human actor.
REGISTER = Actor(
    "svc-evidence-register", "Evidence register", Role.SYSTEM, frozenset({Role.SYSTEM})
)

# Hooks registered by the decisions feature: (session, case, new_snapshot_hash) -> ids of
# approvals marked stale. Each returned id gets an `approval.stale` event.
STALE_APPROVAL_HOOKS: list[Callable[[Session, Case, str], list[str]]] = []


def policy_material(case: Case) -> dict[str, Any]:
    return {
        "policy_version": case.policy_version,
        "receipt_threshold_cents": RECEIPT_THRESHOLD_CENTS,
    }


def _current(session: Session, case_id: str) -> list[tuple[EvidenceRecord, EvidenceVersion]]:
    latest = (
        select(EvidenceVersion.record_id, func.max(EvidenceVersion.version).label("v"))
        .group_by(EvidenceVersion.record_id)
        .subquery()
    )
    rows = session.execute(
        select(EvidenceRecord, EvidenceVersion)
        .join(EvidenceVersion, EvidenceVersion.record_id == EvidenceRecord.id)
        .join(
            latest,
            (latest.c.record_id == EvidenceVersion.record_id)
            & (latest.c.v == EvidenceVersion.version),
        )
        .where(EvidenceRecord.case_id == case_id)
        .order_by(EvidenceRecord.created_at, EvidenceRecord.id)
    ).all()
    return [(r, v) for r, v in rows]


def _review_material(session: Session, case_id: str) -> dict[str, Any]:
    """Stored record statuses and open conflict findings: what a review decision changes."""
    conflicts = session.scalars(
        select(Finding.id).where(
            Finding.case_id == case_id,
            Finding.kind == "conflict",
            Finding.status == FindingStatus.OPEN.value,
        )
    ).all()
    return {
        "statuses": {r.id: r.status for r, _ in _current(session, case_id)},
        "open_conflicts": sorted(conflicts),
    }


def recompute_snapshot(session: Session, case: Case) -> str:
    """Store and return the bare hex hash over current material versions, policy fields and
    review state (record statuses, open conflicts)."""
    triples = [(r.id, v.material_version, v.content_hash) for r, v in _current(session, case.id)]
    digest = compute_snapshot_hash(
        triples, policy_material(case), _review_material(session, case.id)
    )
    case.evidence_snapshot = SNAPSHOT_PREFIX + digest
    return digest


def _case(session: Session, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise CommandError("case_not_found", 404, "No such case.")
    return case


def _version(session: Session, record_id: str, version: int) -> EvidenceVersion | None:
    return session.scalars(
        select(EvidenceVersion).where(
            EvidenceVersion.record_id == record_id, EvidenceVersion.version == version
        )
    ).first()


def read_evidence_field(
    session: Session, case_id: str, record_id: str, field: str
) -> tuple[Any, int]:
    """Value of a field on the record's current version, with that version (for grounding)."""
    for rec, ver in _current(session, case_id):
        if rec.id == record_id:
            if field not in ver.fields:
                raise CommandError(
                    "evidence_field_not_found", 404, f"{record_id} has no '{field}'."
                )
            return ver.fields[field], ver.version
    raise CommandError("evidence_not_found", 404, f"No evidence record '{record_id}'.")


def _open_conflicts(session: Session, case_id: str) -> list[OpenConflict]:
    findings = session.scalars(
        select(Finding)
        .where(
            Finding.case_id == case_id,
            Finding.kind == "conflict",
            Finding.status == FindingStatus.OPEN.value,
        )
        .order_by(Finding.created_at, Finding.id)
    ).all()
    current = {r.id: v.version for r, v in _current(session, case_id)}
    out: list[OpenConflict] = []
    for f in findings:
        links = session.scalars(
            select(FindingLink).where(FindingLink.finding_id == f.id).order_by(FindingLink.id)
        ).all()
        if any(current.get(link.record_id) != link.version for link in links):
            continue  # cites a superseded version: not an open conflict on current evidence
        values = []
        for link in links:
            ver = _version(session, link.record_id, link.version)
            assert ver is not None
            values.append(
                ConflictValue(
                    record_id=link.record_id, version=link.version, value=ver.fields[link.field]
                )
            )
        out.append(
            OpenConflict(
                finding_id=f.id,
                record_ids=list(dict.fromkeys(link.record_id for link in links)),
                field=f.conflict_field or "",
                values=values,
            )
        )
    return out


def get_evidence_summary(session: Session, case_id: str) -> EvidenceSummary:
    case = _case(session, case_id)
    conflicts = _open_conflicts(session, case_id)
    conflicting = {rid for c in conflicts for rid in c.record_ids}
    current = _current(session, case_id)
    records = [
        RecordSummary(
            record_id=r.id,
            kind=r.kind,
            status=EvidenceStatus.CONFLICTING if r.id in conflicting else EvidenceStatus(r.status),
            current_version=v.version,
            fields=v.fields,
        )
        for r, v in current
    ]
    have = {r.kind for r, _ in current}
    missing = [k.value for k in REQUIRED_KINDS if k.value not in have]
    return EvidenceSummary(
        snapshot_hash=case.evidence_snapshot.removeprefix(SNAPSHOT_PREFIX),
        records=records,
        open_conflicts=conflicts,
        missing=missing,
    )


class CheckView(BaseModel):
    key: str
    label: str
    kinds: list[str]
    status: str
    stale_reason: str | None


class FindingView(BaseModel):
    finding_id: str
    kind: str
    statement: str
    status: str
    resolved_by: str | None
    links: list[dict[str, Any]]


class EvidenceRegister(EvidenceSummary):
    checks: list[CheckView]
    findings: list[FindingView]


class VersionView(BaseModel):
    version: int
    material_version: int
    status: str  # current | superseded
    fields: dict[str, Any]
    content_hash: str
    source: str
    created_by: str
    created_at: datetime
    attachments: list[dict[str, Any]]


class RecordDetail(BaseModel):
    record_id: str
    kind: str
    status: EvidenceStatus
    current_version: int
    versions: list[VersionView]
    findings: list[FindingView]


def _finding_views(
    session: Session, case_id: str, record_id: str | None = None
) -> list[FindingView]:
    out: list[FindingView] = []
    for f in session.scalars(
        select(Finding).where(Finding.case_id == case_id).order_by(Finding.created_at, Finding.id)
    ):
        links = session.scalars(
            select(FindingLink).where(FindingLink.finding_id == f.id).order_by(FindingLink.id)
        ).all()
        if record_id is not None and record_id not in {link.record_id for link in links}:
            continue
        out.append(
            FindingView(
                finding_id=f.id,
                kind=f.kind,
                statement=f.statement,
                status=f.status,
                resolved_by=f.resolved_by,
                links=[
                    {"record_id": link.record_id, "version": link.version, "field": link.field}
                    for link in links
                ],
            )
        )
    return out


def get_register(session: Session, case_id: str) -> EvidenceRegister:
    summary = get_evidence_summary(session, case_id)
    checks = session.scalars(
        select(EvidenceCheck).where(EvidenceCheck.case_id == case_id).order_by(EvidenceCheck.key)
    ).all()
    return EvidenceRegister(
        **summary.model_dump(),
        checks=[
            CheckView(
                key=c.key,
                label=c.label,
                kinds=list(c.kinds),
                status=c.status,
                stale_reason=c.stale_reason,
            )
            for c in checks
        ],
        findings=_finding_views(session, case_id),
    )


def get_record_detail(session: Session, case_id: str, record_id: str) -> RecordDetail:
    _case(session, case_id)
    rec = session.get(EvidenceRecord, record_id)
    if rec is None or rec.case_id != case_id:
        raise CommandError("evidence_not_found", 404, f"No evidence record '{record_id}'.")
    versions = session.scalars(
        select(EvidenceVersion)
        .where(EvidenceVersion.record_id == record_id)
        .order_by(EvidenceVersion.version.desc())
    ).all()
    summary = next(
        r for r in get_evidence_summary(session, case_id).records if r.record_id == record_id
    )
    views = []
    for i, v in enumerate(versions):
        atts = session.scalars(
            select(Attachment).where(
                Attachment.record_id == record_id, Attachment.version == v.version
            )
        ).all()
        views.append(
            VersionView(
                version=v.version,
                material_version=v.material_version,
                status="current" if i == 0 else EvidenceStatus.SUPERSEDED.value,
                fields=v.fields,
                content_hash=v.content_hash,
                source=v.source,
                created_by=v.created_by,
                created_at=v.created_at,
                attachments=[
                    {
                        "file_name": a.file_name,
                        "content_type": a.content_type,
                        "size_bytes": a.size_bytes,
                        "sha256": a.sha256,
                        "uploader": a.uploader,
                    }
                    for a in atts
                ],
            )
        )
    return RecordDetail(
        record_id=rec.id,
        kind=rec.kind,
        status=summary.status,
        current_version=versions[0].version,
        versions=views,
        findings=_finding_views(session, case_id, record_id),
    )


# ---- command side effects (run by the gateway inside its transaction) --------------------------


def _check_ref(session: Session, case_id: str, record_id: str, version: int, field: str) -> None:
    rec = session.get(EvidenceRecord, record_id)
    if rec is None or rec.case_id != case_id:
        raise CommandError("schema_invalid", 422, f"links: unknown source record '{record_id}'.")
    ver = _version(session, record_id, version)
    if ver is None:
        raise CommandError("schema_invalid", 422, f"links: {record_id} has no version {version}.")
    latest = session.scalars(
        select(func.max(EvidenceVersion.version)).where(EvidenceVersion.record_id == record_id)
    ).one()
    if version != latest:
        raise CommandError(
            "schema_invalid", 422, f"links: {record_id} v{version} is superseded by v{latest}."
        )
    if field not in ver.fields:
        raise CommandError(
            "schema_invalid", 422, f"links: {record_id} v{version} has no '{field}'."
        )


def _own_finding(session: Session, case_id: str, finding_id: str) -> Finding:
    finding = session.get(Finding, finding_id)
    if finding is None or finding.case_id != case_id:
        raise CommandError("finding_not_found", 404, f"No finding '{finding_id}' on this case.")
    return finding


def _effect_link(
    session: Session, case: Case, p: Any, now: datetime, actor_id: str
) -> dict[str, Any]:
    _own_finding(session, case.id, p.finding_id)
    _check_ref(session, case.id, p.record_id, p.version, p.field)
    exists = session.scalars(
        select(FindingLink).where(
            FindingLink.finding_id == p.finding_id,
            FindingLink.record_id == p.record_id,
            FindingLink.version == p.version,
            FindingLink.field == p.field,
        )
    ).first()
    if exists is not None:
        raise CommandError("schema_invalid", 422, "That link already exists on the finding.")
    session.add(
        FindingLink(
            finding_id=p.finding_id, record_id=p.record_id, version=p.version, field=p.field
        )
    )
    session.flush()
    return {}


def _effect_claim(
    session: Session, case: Case, p: Any, now: datetime, actor_id: str
) -> dict[str, Any]:
    report = session.get(Report, p.report_id)
    if report is None or report.case_id != case.id:
        raise CommandError(
            "schema_invalid", 422, f"report_id: '{p.report_id}' is not on this case."
        )
    if session.get(Claim, p.claim_id) is not None:
        raise CommandError("schema_invalid", 422, f"claim_id: '{p.claim_id}' already exists.")
    session.add(Claim(id=p.claim_id, report_id=p.report_id, case_id=case.id, statement=p.statement))
    session.flush()
    return {}


def _effect_finding(
    session: Session, case: Case, p: Any, now: datetime, actor_id: str
) -> dict[str, Any]:
    if session.get(Finding, p.finding_id) is not None:
        raise CommandError("schema_invalid", 422, f"finding_id: '{p.finding_id}' already exists.")
    for link in p.links:
        _check_ref(session, case.id, link.record_id, link.version, link.field)
    session.add(
        Finding(
            id=p.finding_id,
            case_id=case.id,
            kind=p.kind,
            statement=p.statement,
            status=p.status.value,
            resolved_by=p.resolved_by,
            conflict_field=p.conflict_field,
            created_by=actor_id,
            created_at=now,
        )
    )
    session.flush()
    for link in p.links:
        session.add(
            FindingLink(
                finding_id=p.finding_id,
                record_id=link.record_id,
                version=link.version,
                field=link.field,
            )
        )
    session.flush()
    return {}


def _effect_status(
    session: Session, case: Case, p: Any, now: datetime, actor_id: str
) -> dict[str, Any]:
    rec = session.get(EvidenceRecord, p.record_id)
    if rec is None or rec.case_id != case.id:
        raise CommandError("evidence_not_found", 404, f"No evidence record '{p.record_id}'.")
    prior = rec.status
    if prior == p.status:
        raise CommandError("evidence_status_unchanged", 409, f"{rec.id} is already {prior}.")
    rec.status = p.status
    session.flush()
    recompute_snapshot(session, case)
    return {"prior_status": prior}


def _effect_resolve(
    session: Session, case: Case, p: Any, now: datetime, actor_id: str
) -> dict[str, Any]:
    finding = _own_finding(session, case.id, p.finding_id)
    if finding.status != FindingStatus.OPEN.value:
        raise CommandError(
            "finding_not_open", 409, f"Finding {finding.id} is {finding.status}, not open."
        )
    finding.status = FindingStatus.RESOLVED.value
    finding.resolved_by = p.resolved_by
    links = session.scalars(
        select(FindingLink.record_id).where(FindingLink.finding_id == finding.id)
    ).all()
    session.flush()
    recompute_snapshot(session, case)
    # A linked record reads `conflicting` only while an open conflict cites it, so it returns
    # to its stored status (supporting) once no other open conflict references it.
    return {"record_ids": list(dict.fromkeys(links))}


def _effect_version(
    session: Session, case: Case, p: Any, now: datetime, actor_id: str, actor_role: Role
) -> dict[str, Any]:
    rec = session.get(EvidenceRecord, p.record_id)
    if rec is None or rec.case_id != case.id:
        raise CommandError("evidence_not_found", 404, f"No evidence record '{p.record_id}'.")
    prior_hash = case.evidence_snapshot.removeprefix(SNAPSHOT_PREFIX)
    prev = max(
        session.scalars(select(EvidenceVersion).where(EvidenceVersion.record_id == rec.id)),
        key=lambda v: v.version,
    )
    new_hash = content_hash(rec.kind, p.fields)
    material = new_hash != prev.content_hash
    version = prev.version + 1
    session.add(
        EvidenceVersion(
            record_id=rec.id,
            version=version,
            material_version=prev.material_version + (1 if material else 0),
            fields=p.fields,
            content_hash=new_hash,
            source=p.source,
            created_by=actor_id,
            created_at=now,
        )
    )
    session.flush()
    if p.attachment is not None:
        session.add(
            Attachment(
                record_id=rec.id,
                version=version,
                uploader=actor_id,
                created_at=now,
                **p.attachment.model_dump(),
            )
        )
    stale_checks: list[str] = []
    stale_approvals: list[str] = []
    stale_findings: list[str] = []
    snapshot = prior_hash
    if material:
        for check in session.scalars(select(EvidenceCheck).where(EvidenceCheck.case_id == case.id)):
            if rec.kind in check.kinds:
                stale_checks.append(check.key)
                if check.status != "stale":
                    check.status = "stale"
                    check.stale_reason = f"{rec.id} v{version} changed"
                    check.stale_at = now
        stale_findings = _stale_findings(session, case, rec.id, version)
        snapshot = recompute_snapshot(session, case)
        for hook in STALE_APPROVAL_HOOKS:
            stale_approvals.extend(hook(session, case, snapshot))
    session.flush()
    return {
        "result": {
            "record_id": rec.id,
            "version": version,
            "material": material,
            "snapshot_hash": snapshot,
            "prior_snapshot_hash": prior_hash,
            "stale_checks": stale_checks,
            "stale_approvals": stale_approvals,
            "stale_findings": stale_findings,
        }
    }


def _stale_findings(session: Session, case: Case, record_id: str, version: int) -> list[str]:
    """Open findings citing an older version of the record go stale with the material change."""
    stale = session.scalars(
        select(Finding)
        .join(FindingLink, FindingLink.finding_id == Finding.id)
        .where(
            Finding.case_id == case.id,
            Finding.status == FindingStatus.OPEN.value,
            FindingLink.record_id == record_id,
            FindingLink.version < version,
        )
        .distinct()
        .order_by(Finding.id)
    ).all()
    for finding in stale:
        finding.status = FindingStatus.STALE.value
    return [f.id for f in stale]


def after_effect(
    session: Session,
    case: Case,
    command: str,
    extra: dict[str, Any],
    *,
    now: datetime,
    actor_id: str,
    actor_role: Role,
) -> None:
    """Runs after the command's own event (evidence.version_added), same transaction, so the
    audit order is version_added -> finding.stale -> approval.stale -> policy.evaluated."""
    if command in ("set_record_status", "resolve_finding"):
        # A review decision is a new snapshot: re-evaluate a case that has been evaluated.
        if policy_service.has_evaluation(session, case.id):
            policy_service.reevaluate_on_evidence_change(session, case.id, now)
        return
    if command != "append_evidence_version" or not extra["result"]["material"]:
        return
    res = extra["result"]
    detail = {"record_id": res["record_id"], "version": res["version"]}
    for finding_id in res["stale_findings"]:
        _emit(
            session,
            EventType.FINDING_STALE,
            case,
            actor_id,
            actor_role,
            now,
            [finding_id, res["record_id"]],
            f"Finding {finding_id} is out of date: {res['record_id']} v{res['version']} changed",
            detail,
        )
    for approval_id in res["stale_approvals"]:
        _emit(
            session,
            EventType.APPROVAL_STALE,
            case,
            actor_id,
            actor_role,
            now,
            [approval_id],
            f"Approval {approval_id} is out of date: {res['record_id']} changed",
            {**detail, "snapshot_hash": res["snapshot_hash"]},
        )
    # Re-evaluate only a case that has been evaluated before: a material change never creates
    # the first evaluation implicitly (that is the analyst's evaluate_policy command).
    if policy_service.has_evaluation(session, case.id):
        policy_service.reevaluate_on_evidence_change(session, case.id, now)


def run_effect(
    session: Session,
    case: Case,
    command: str,
    model: Any,
    *,
    now: datetime,
    actor_id: str,
    actor_role: Role,
) -> dict[str, Any]:
    if command == "append_evidence_version":
        return _effect_version(session, case, model, now, actor_id, actor_role)
    simple = {
        "link_evidence": _effect_link,
        "record_claim": _effect_claim,
        "record_finding": _effect_finding,
        "set_record_status": _effect_status,
        "resolve_finding": _effect_resolve,
    }
    return simple[command](session, case, model, now, actor_id)


def run_service_command(
    session: Session,
    case: Case,
    command: str,
    payload: dict[str, Any],
    *,
    actor: Actor,
    now: datetime,
    request_id: str,
) -> "Outcome":
    """An evidence service command run by another command's after-effect, inside that command's
    transaction on the already locked case. Same role, schema, key and replay rules as the
    gateway; the write itself is the gateway's stage 9 (write_command), so it gets its own
    idempotency key, event, version and state transition."""
    spec = SERVICE_REGISTRY[command]
    check_role(spec, actor.active_role)
    model = spec.payload_model.model_validate(payload)
    body = model.model_dump(mode="json")
    key = resolve_key(spec, {"case_id": case.id, "case_version": case.case_version, **body})
    req_hash = gateway.request_hash(spec.name, actor.user_id, actor.active_role, body)
    existing = gateway.find_key(session, key, case.id, spec.name, req_hash)
    if existing is not None:
        return gateway.replay(existing, now)
    return gateway.write_command(
        session,
        case,
        spec,
        model,
        key=key,
        req_hash=req_hash,
        actor_id=actor.user_id,
        actor_name=actor.name,
        actor_role=actor.active_role,
        request_id=request_id,
        now=now,
    )


def set_status_once(
    session: Session, case: Case, record_id: str, status: str, reason: str, now: datetime
) -> bool:
    """set_record_status unless the record already holds that status. True if it changed."""
    rec = session.get(EvidenceRecord, record_id)
    if rec is None or rec.case_id != case.id or rec.status == status:
        return False
    run_service_command(
        session,
        case,
        "set_record_status",
        {"record_id": record_id, "status": status, "reason": reason},
        actor=REGISTER,
        now=now,
        request_id=f"evidence:{record_id}:{status}",
    )
    return True


def resolve_open_conflicts(
    session: Session, case: Case, resolved_by: str, actor: Actor, now: datetime
) -> list[str]:
    """resolve_finding for every open conflict finding on the case; returns their ids."""
    ids = session.scalars(
        select(Finding.id)
        .where(
            Finding.case_id == case.id,
            Finding.kind == "conflict",
            Finding.status == FindingStatus.OPEN.value,
        )
        .order_by(Finding.created_at, Finding.id)
    ).all()
    for finding_id in ids:
        run_service_command(
            session,
            case,
            "resolve_finding",
            {"finding_id": finding_id, "resolved_by": resolved_by},
            actor=actor,
            now=now,
            request_id=f"resolve:{finding_id}",
        )
    return list(ids)


# ---- review_related_charge (analyst; registered with the gateway's built-in handlers) ------------


def related_effect(
    session: Session, case: Case, actor: Actor, p: Any, now: datetime, ctx: "EffectContext"
) -> dict[str, Any]:
    rec = session.get(EvidenceRecord, p.record_id)
    if rec is None or rec.case_id != case.id or rec.kind != "related_charge":
        raise CommandError(
            "evidence_not_found", 404, f"No related charge '{p.record_id}' on this case."
        )
    if rec.status != EvidenceStatus.PENDING_REVIEW.value:
        raise CommandError(
            "related_charge_reviewed", 409, f"{rec.id} was already reviewed ({rec.status})."
        )
    status = "supporting" if p.decision == "related" else "not_relevant"
    return {"status": status}


def related_after(
    session: Session,
    case: Case,
    actor: Actor,
    p: Any,
    now: datetime,
    ctx: "EffectContext",
    out: "Outcome",
) -> None:
    status = str(ctx.extra["status"])
    word = "related" if p.decision == "related" else "not related"
    set_status_once(
        session, case, p.record_id, status, f"{actor.name}: {word} · {p.reason}"[:500], now
    )


# ---- seed ---------------------------------------------------------------------------------------

# Source records only. No finding is pre-written: conclusions come from a run.
_SEED_RECORDS: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
    (
        "CHG-1042",
        "charge",
        "supporting",
        {
            "merchant": "Bayline Industrial Supply",
            "amount_cents": 284000,
            "currency": "USD",
            "card_last4": "4418",
            "cardholder_id": "chd-priya-shah",
        },
    ),
    (
        "PO-219",
        "purchase_order",
        "supporting",
        {
            "approved_quantity": 1,
            "approved_amount_cents": 240000,
            "merchant": "Bayline Industrial Supply",
        },
    ),
    ("DLV-882", "delivery_record", "supporting", {"received_quantity": 2}),
    (
        "REP-1042",
        "initial_report",
        "pending_review",
        {"statement": "I do not recognize this charge."},
    ),
    (
        "PRF-4418",
        "cardholder_profile",
        "supporting",
        {"name": "Priya Shah", "phone": "(415) 555-0182", "verification_target": "phone"},
    ),
    (
        "CHG-1051",
        "related_charge",
        "pending_review",
        {"merchant": "Bayline Industrial Supply", "amount_cents": 120000},
    ),
    ("CHG-1048", "related_charge", "pending_review", {"amount_cents": 62000}),
)


def seed_evidence(session: Session, now: datetime) -> None:
    case = session.get(Case, SEED_CASE)
    assert case is not None
    txn = session.get(CardTransaction, case.transaction_id)
    assert txn is not None
    for rid, kind, status, seed_fields in _SEED_RECORDS:
        fields = dict(seed_fields)
        if rid == SEED_CASE:
            fields["posted_at"] = txn.posted_at.isoformat()
        session.add(EvidenceRecord(id=rid, case_id=SEED_CASE, kind=kind, status=status))
        session.flush()
        session.add(
            EvidenceVersion(
                record_id=rid,
                version=1,
                material_version=1,
                fields=fields,
                content_hash=content_hash(kind, fields),
                source="synthetic seed",
                created_by="seed",
                created_at=now,
            )
        )
    for key, label, kinds in CHECKS:
        session.add(EvidenceCheck(case_id=SEED_CASE, key=key, label=label, kinds=list(kinds)))
    session.flush()
    recompute_snapshot(session, case)


# ---- routes -------------------------------------------------------------------------------------


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def _actor(request: Request, session: Annotated[Session, Depends(_session)]) -> Actor:
    settings: Settings = request.app.state.settings
    return auth.load_actor(
        session, settings.secret(), request.cookies.get(auth.COOKIE), settings.synthetic
    )


DbSession = Annotated[Session, Depends(_session)]
ReaderDep = Annotated[Actor, Depends(_actor)]


def _require_reader(actor: Actor) -> None:
    if actor.active_role not in STAFF_ROLES or actor.active_role not in actor.roles:
        raise CommandError("role_forbidden", 403, "This role cannot read the evidence register.")


router = APIRouter(prefix="/api")
demo_router = APIRouter(prefix="/api/demo")  # synthetic environment only


@router.get("/cases/{case_id}/evidence")
def get_evidence(case_id: str, session: DbSession, actor: ReaderDep) -> EvidenceRegister:
    _require_reader(actor)
    return get_register(session, case_id)


@router.get("/cases/{case_id}/evidence/{record_id}")
def get_evidence_record(
    case_id: str, record_id: str, session: DbSession, actor: ReaderDep
) -> RecordDetail:
    _require_reader(actor)
    return get_record_detail(session, case_id, record_id)


class MaterialChangeIn(BaseModel):
    case_id: str = SEED_CASE
    record_id: str = "DLV-882"
    fields: dict[str, Any] | None = None  # required unless record_id is DLV-882 (default qty 1)
    source: str = "delivery system (demo)"


class MaterialChangeOut(BaseModel):
    before: EvidenceSummary
    after: EvidenceSummary
    version: int
    material: bool
    stale_checks: list[str]
    event_ids: list[str]


@demo_router.post("/material-change")
def material_change(
    body: MaterialChangeIn, request: Request, session: DbSession
) -> MaterialChangeOut:
    clock: Clock = request.app.state.clock
    before = get_evidence_summary(session, body.case_id)
    current = next((r for r in before.records if r.record_id == body.record_id), None)
    if current is None:
        raise CommandError("evidence_not_found", 404, f"No evidence record '{body.record_id}'.")
    if body.fields is None and body.record_id != "DLV-882":
        raise CommandError("schema_invalid", 422, "fields: required for this record.")
    fields = body.fields or {**current.fields, "received_quantity": 1}
    case = _case(session, body.case_id)
    spec = SERVICE_REGISTRY["append_evidence_version"]
    system = Actor("svc-source-system", "Source system", Role.SYSTEM, frozenset({Role.SYSTEM}))
    key = spec.key_template.format(
        case_id=case.id, record_id=body.record_id, case_version=case.case_version
    )
    version = case.case_version
    session.rollback()
    out = gateway.execute_command(
        session,
        now=clock.now(),
        case_id=body.case_id,
        command="append_evidence_version",
        key=key,
        expected_version=version,
        payload={"record_id": body.record_id, "fields": fields, "source": body.source},
        actor=system,
        request_id=request.headers.get("x-request-id") or uuid.uuid4().hex,
    )
    return MaterialChangeOut(
        before=before,
        after=get_evidence_summary(session, body.case_id),
        version=out.result["version"],
        material=out.result["material"],
        stale_checks=out.result["stale_checks"],
        event_ids=out.event_ids,
    )
