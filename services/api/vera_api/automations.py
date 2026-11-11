"""Automations versioning (VER-014): organization-level commands and reads.

Commands run through POST /api/automations/commands/{name} with the gateway's guarantees:
role re-checked against user_roles (gateway._recheck_role) and ops_admin only, schema
validation, idempotency bound to command+user+role+payload (gateway.request_hash), a version
check and audit events. audit_events and idempotency_keys require a case_id, so the keys and
events live in automation_command_keys / automation_events (append-only), read via
GET /api/automations/events.
"""

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vera_domain import automations as dom
from vera_domain.commands import Payload
from vera_domain.enums import Role, register_event_types
from vera_domain.errors import CommandError
from vera_domain.labels import register_event_summaries

from vera_api import auth, plugins
from vera_api.auth import STAFF_ROLES, Actor
from vera_api.gateway import _recheck_role, request_hash
from vera_api.models_automations import (
    AutomationCommandKey,
    AutomationEvent,
    PolicyDraft,
    SpecialistDefinition,
    WorkflowCheckRun,
    WorkflowDefinition,
    WorkflowDraft,
    WorkflowVersion,
)
from vera_api.models_policy import PolicyVersionRow

V3 = 3
EVENTS = {
    "workflow.draft_created": "Workflow draft created",
    "workflow.draft_updated": "Workflow draft updated",
    "workflow.checks_completed": "Workflow checks completed",
    "workflow.published": "Workflow version published",
    "workflow.draft_discarded": "Workflow draft discarded",
    "specialist.draft_created": "Specialist draft created",
    "specialist.draft_updated": "Specialist draft updated",
    "policy.draft_created": "Policy draft created",
    "policy.published": "Policy version published",
}
register_event_types(*EVENTS)
register_event_summaries(EVENTS)


# ---- seed and lookups ---------------------------------------------------------------------------


def ensure_seeded(session: Session) -> None:
    """Workflow v3 as data (idempotent; re-created after a demo reset)."""
    if session.get(WorkflowDefinition, dom.WORKFLOW_ID) is not None:
        return
    session.add(WorkflowDefinition(id=dom.WORKFLOW_ID, name="Card dispute", active_version=V3))
    session.flush()
    session.add(
        WorkflowVersion(
            workflow_id=dom.WORKFLOW_ID,
            version=V3,
            graph=dom.WORKFLOW_V3.model_dump(mode="json"),
            graph_hash=dom.graph_hash(dom.WORKFLOW_V3),
            published_by="seed",
            reason="Seeded workflow v3",
            created_at=func.now(),
        )
    )
    session.flush()


def active_workflow_version(session: Session, workflow_id: str = dom.WORKFLOW_ID) -> int:
    """The version new cases should pin (for intake/start_investigation)."""
    ensure_seeded(session)
    wf = session.get(WorkflowDefinition, workflow_id)
    if wf is None:
        raise CommandError("workflow_not_found", 404, "No such workflow.")
    return wf.active_version


def active_graph(session: Session, workflow_id: str = dom.WORKFLOW_ID) -> dom.Graph:
    v = active_workflow_version(session, workflow_id)
    row = session.get(WorkflowVersion, (workflow_id, v))
    assert row is not None
    return dom.Graph.model_validate(row.graph)


def _draft(session: Session, workflow_id: str, version: int) -> WorkflowDraft:
    ensure_seeded(session)
    row = session.get(WorkflowDraft, (workflow_id, version))
    if row is None:
        raise CommandError("draft_not_found", 404, f"No open draft v{version}.")
    return row


def _violations_error(violations: list[dom.Violation], code: str) -> CommandError:
    first = violations[0]
    err = CommandError(
        code,
        422,
        f"Rule {first.rule} ({first.rule_name}) · {', '.join(first.node_ids)}: {first.message}",
        blocked_reason=first.message,
    )
    err.violations = [v.model_dump() for v in violations]  # type: ignore[attr-defined]
    return err


def _latest_policy(session: Session, policy_id: str) -> int:
    top = session.scalars(
        select(func.max(PolicyVersionRow.version)).where(PolicyVersionRow.policy_id == policy_id)
    ).first()
    if top is None:
        raise CommandError("policy_not_found", 404, "No such policy.")
    return int(top)


# ---- command handlers ---------------------------------------------------------------------------


@dataclass
class Done:
    result: dict[str, Any]
    event: str
    record_ids: list[str]
    summary: str


Handler = Callable[[Session, Actor, Any, datetime], Done]
Current = Callable[[Session, Any], int]


def _create_draft(
    session: Session, workflow_id: str, from_version: int, actor: Actor, now: datetime
) -> WorkflowDraft:
    if active_workflow_version(session, workflow_id) != from_version:
        raise CommandError("stale_version", 409, "Drafts start from the active version.")
    if session.scalars(
        select(WorkflowDraft).where(WorkflowDraft.workflow_id == workflow_id)
    ).first():
        raise CommandError("draft_exists", 409, "This workflow already has an open draft.")
    top = session.scalars(
        select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow_id)
    ).one()
    src = session.get(WorkflowVersion, (workflow_id, from_version))
    assert src is not None
    row = WorkflowDraft(
        workflow_id=workflow_id,
        version=int(top) + 1,
        from_version=from_version,
        graph=src.graph,
        revision=0,
        created_by=actor.user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


def _h_create_draft(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    row = _create_draft(session, p.workflow_id, p.from_version, actor, now)
    return Done(
        {"draft_version": row.version},
        "workflow.draft_created",
        [f"{p.workflow_id}:draft:{row.version}"],
        f"Draft v{row.version} created",
    )


def _h_update_draft(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    row = _draft(session, p.workflow_id, p.draft_version)
    try:
        graph = dom.apply_patch(dom.Graph.model_validate(row.graph), p.ops)
    except dom.PatchError as exc:
        raise _violations_error(exc.violations, "required_control_removed") from None
    row.graph = graph.model_dump(mode="json")
    row.revision += 1
    row.updated_at = now
    session.flush()
    issues = [v.model_dump() for v in dom.validate(graph)]
    return Done(
        {"draft_version": row.version, "revision": row.revision, "validation": issues},
        "workflow.draft_updated",
        [f"{p.workflow_id}:draft:{row.version}"],
        f"Draft v{row.version} updated",
    )


def _h_run_checks(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    row = _draft(session, p.workflow_id, p.draft_version)
    graph = dom.Graph.model_validate(row.graph)
    results = dom.run_checks(graph)
    run = WorkflowCheckRun(
        workflow_id=p.workflow_id,
        draft_version=row.version,
        graph_hash=dom.graph_hash(graph),
        passed=all(r.passed for r in results),
        results=[r.model_dump(mode="json") for r in results],
        created_at=now,
    )
    session.add(run)
    session.flush()
    return Done(
        {
            "run_id": run.id,
            "graph_hash": run.graph_hash,
            "passed": run.passed,
            "results": [{k: v for k, v in r.items() if k != "trace"} for r in run.results],
        },
        "workflow.checks_completed",
        [f"CHECK-{run.id}"],
        f"Checks {'passed' if run.passed else 'failed'} on draft v{row.version}",
    )


def _h_publish(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    row = _draft(session, p.workflow_id, p.draft_version)
    graph = dom.Graph.model_validate(row.graph)
    issues = dom.validate(graph)
    if issues:
        raise _violations_error(issues, "validation_failed")
    gh = dom.graph_hash(graph)
    run = session.scalars(
        select(WorkflowCheckRun)
        .where(
            WorkflowCheckRun.workflow_id == p.workflow_id,
            WorkflowCheckRun.draft_version == row.version,
        )
        .order_by(WorkflowCheckRun.id.desc())
    ).first()
    if run is None or run.graph_hash != gh:
        raise CommandError(
            "checks_required",
            422,
            "Run workflow checks on this exact draft.",
            blocked_reason="Checks have not run on this draft graph.",
        )
    if not run.passed:
        raise CommandError(
            "checks_failed",
            422,
            "Every scenario must reach an end state.",
            blocked_reason="A scenario did not reach Close or monitor.",
        )
    session.add(
        WorkflowVersion(
            workflow_id=p.workflow_id,
            version=row.version,
            graph=row.graph,
            graph_hash=gh,
            published_by=actor.user_id,
            reason=p.reason,
            created_at=now,
        )
    )
    wf = session.get(WorkflowDefinition, p.workflow_id)
    assert wf is not None
    old = wf.active_version
    wf.active_version = row.version
    session.delete(row)
    session.flush()
    return Done(
        {"active_version": wf.active_version},
        "workflow.published",
        [f"{p.workflow_id}:v{wf.active_version}"],
        f"Published v{wf.active_version}. Running cases remain pinned to v{old}.",
    )


def _h_discard(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    row = _draft(session, p.workflow_id, p.draft_version)
    session.delete(row)
    session.flush()
    return Done(
        {"discarded_version": p.draft_version},
        "workflow.draft_discarded",
        [f"{p.workflow_id}:draft:{p.draft_version}"],
        "Draft discarded",
    )


def _check_tools(fields: dom.SpecialistFields) -> None:
    bad = dom.prohibited_tools(fields.tools)
    if bad:
        raise CommandError(
            "prohibited_tool", 422, f"tools: {', '.join(bad)} is not in the approved tool library."
        )


def _h_create_spec(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    _check_tools(p)
    if session.get(SpecialistDefinition, p.specialist_id) is not None:
        raise CommandError("specialist_exists", 409, "That specialist already exists.")
    fields = p.model_dump(mode="json", exclude={"specialist_id"})
    session.add(
        SpecialistDefinition(
            id=p.specialist_id,
            status="draft",
            fields=fields,
            revision=0,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    return Done(
        {"specialist_id": p.specialist_id, "status": "draft"},
        "specialist.draft_created",
        [p.specialist_id],
        "Specialist draft created",
    )


def _spec_row(session: Session, specialist_id: str) -> SpecialistDefinition:
    row = session.get(SpecialistDefinition, specialist_id)
    if row is None:
        raise CommandError("specialist_not_found", 404, "No such specialist.")
    return row


def _h_update_spec(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    _check_tools(p)
    row = _spec_row(session, p.specialist_id)
    if row.status != "draft":
        raise CommandError("not_a_draft", 409, "Only a draft specialist can be edited.")
    row.fields = p.model_dump(mode="json", exclude={"specialist_id"})
    row.revision += 1
    row.updated_at = now
    session.flush()
    return Done(
        {"specialist_id": row.id, "status": row.status, "revision": row.revision},
        "specialist.draft_updated",
        [row.id],
        "Specialist draft updated",
    )


def _h_add_spec(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    spec = _spec_row(session, p.specialist_id)
    fields = dom.SpecialistFields.model_validate(spec.fields)
    _check_tools(fields)
    draft = _create_draft(session, p.workflow_id, p.from_version, actor, now)
    graph = dom.Graph.model_validate(draft.graph)
    after = graph.node(p.after_node)
    if after is None or len(after.outcomes) != 1:
        raise CommandError(
            "schema_invalid", 422, f"after_node: '{p.after_node}' cannot host a step."
        )
    outgoing = [e for e in graph.edges if e.source == after.key]
    node_id = f"{spec.id}_1"
    ops = [
        dom.PatchOp(
            op="add_node",
            node=dom.Node(
                key=node_id,
                kind="finance_specialist",
                label=fields.name,
                category="agent",
                outcomes=after.outcomes,
                specialist_id=spec.id,
            ),
        )
    ]
    for e in outgoing:
        ops += [
            dom.PatchOp(op="remove_edge", edge=e),
            dom.PatchOp(
                op="add_edge",
                edge=dom.Edge(source=node_id, target=e.target, outcome=e.outcome, max=e.max),
            ),
        ]
    ops.append(
        dom.PatchOp(
            op="add_edge",
            edge=dom.Edge(source=after.key, target=node_id, outcome=after.outcomes[0]),
        )
    )
    draft.graph = dom.apply_patch(graph, ops).model_dump(mode="json")
    draft.revision += 1
    session.flush()
    return Done(
        {"draft_version": draft.version, "node_id": node_id},
        "workflow.draft_created",
        [f"{p.workflow_id}:draft:{draft.version}", spec.id],
        f"Draft v{draft.version} created with {fields.name}",
    )


def _h_create_policy(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    if _latest_policy(session, p.policy_id) != p.from_version:
        raise CommandError("stale_version", 409, "Policy drafts start from the latest version.")
    src = session.get(PolicyVersionRow, (p.policy_id, p.from_version))
    assert src is not None
    if session.scalars(select(PolicyDraft).where(PolicyDraft.policy_id == p.policy_id)).first():
        raise CommandError("draft_exists", 409, "This policy already has an open draft.")
    version = p.from_version + 1
    session.add(
        PolicyDraft(
            policy_id=p.policy_id,
            version=version,
            from_version=p.from_version,
            rules=src.rules,
            created_at=now,
        )
    )
    session.flush()
    return Done(
        {"draft_version": version},
        "policy.draft_created",
        [f"{p.policy_id}:draft:{version}"],
        f"Policy draft v{version} created",
    )


def _h_publish_policy(session: Session, actor: Actor, p: Any, now: datetime) -> Done:
    draft = session.get(PolicyDraft, (p.policy_id, p.draft_version))
    if draft is None:
        raise CommandError("draft_not_found", 404, f"No open policy draft v{p.draft_version}.")
    rules = []
    for rule in draft.rules:
        params = dict(rule.get("params") or {})
        if "threshold_cents" in params:
            params["threshold_cents"] = p.receipt_threshold * 100
        rules.append({**rule, "params": params})
    session.add(PolicyVersionRow(policy_id=p.policy_id, version=draft.version, rules=rules))
    session.delete(draft)
    session.flush()
    return Done(
        {"active_version": draft.version},
        "policy.published",
        [f"{p.policy_id}:v{draft.version}"],
        f"Published policy v{draft.version}. Running cases stay pinned.",
    )


def _cur_active(session: Session, p: Any) -> int:
    return active_workflow_version(session, p.workflow_id)


def _cur_draft(session: Session, p: Any) -> int:
    return _draft(session, p.workflow_id, p.draft_version).revision


def _cur_spec(session: Session, p: Any) -> int:
    row = session.get(SpecialistDefinition, p.specialist_id)
    return row.revision if row else 0


def _cur_policy(session: Session, p: Any) -> int:
    return _latest_policy(session, p.policy_id)


def _ctx_hash(session: Session, p: Any) -> dict[str, object]:
    return {
        "graph_hash": dom.graph_hash(
            dom.Graph.model_validate(_draft(session, p.workflow_id, p.draft_version).graph)
        )
    }


@dataclass(frozen=True)
class AutomationCommand:
    name: str
    payload_model: type[Payload]
    key_template: str
    current_version: Current  # what expected_version is checked against
    handler: Handler
    key_context: Callable[[Session, Any], dict[str, object]] | None = None


COMMANDS = {
    c.name: c
    for c in (
        AutomationCommand(
            "create_workflow_draft",
            dom.CreateWorkflowDraft,
            "wfdraft:{workflow_id}:{from_version}",
            _cur_active,
            _h_create_draft,
        ),
        AutomationCommand(
            "update_workflow_draft",
            dom.UpdateWorkflowDraft,
            "wfpatch:{workflow_id}:{draft_version}:{expected_version}",
            _cur_draft,
            _h_update_draft,
        ),
        AutomationCommand(
            "run_workflow_checks",
            dom.RunWorkflowChecks,
            "wfcheck:{workflow_id}:{draft_version}:{graph_hash}",
            _cur_draft,
            _h_run_checks,
            _ctx_hash,
        ),
        AutomationCommand(
            "publish_workflow_version",
            dom.PublishWorkflowVersion,
            "wfpub:{workflow_id}:{draft_version}",
            _cur_draft,
            _h_publish,
        ),
        AutomationCommand(
            "discard_workflow_draft",
            dom.DiscardWorkflowDraft,
            "wfdiscard:{workflow_id}:{draft_version}",
            _cur_draft,
            _h_discard,
        ),
        AutomationCommand(
            "create_specialist_draft",
            dom.CreateSpecialistDraft,
            "spec:{specialist_id}:new",
            _cur_spec,
            _h_create_spec,
        ),
        AutomationCommand(
            "update_specialist_draft",
            dom.UpdateSpecialistDraft,
            "spec:{specialist_id}:{expected_version}",
            _cur_spec,
            _h_update_spec,
        ),
        AutomationCommand(
            "add_specialist_to_workflow",
            dom.AddSpecialistToWorkflow,
            "spec-wf:{specialist_id}:{workflow_id}:{from_version}",
            _cur_active,
            _h_add_spec,
        ),
        AutomationCommand(
            "create_policy_draft",
            dom.CreatePolicyDraft,
            "poldraft:{policy_id}:{from_version}",
            _cur_policy,
            _h_create_policy,
        ),
        AutomationCommand(
            "publish_policy_version",
            dom.PublishPolicyVersion,
            "polpub:{policy_id}:{draft_version}",
            _cur_policy,
            _h_publish_policy,
        ),
    )
}


def _schema_error(exc: ValidationError) -> CommandError:
    first = exc.errors()[0]
    where = ".".join(str(x) for x in first["loc"]) or "payload"
    return CommandError("schema_invalid", 422, f"{where}: {first['msg']}")


def execute(
    session: Session,
    *,
    now: datetime,
    name: str,
    key: str,
    expected_version: int,
    payload: dict[str, Any],
    actor: Actor,
    request_id: str,
) -> "CommandOut":
    cmd = COMMANDS.get(name)
    if cmd is None:
        raise CommandError("unknown_command", 404, f"Unknown command '{name}'.")
    _recheck_role(session, actor)  # shared: the database must say the user holds the role
    if actor.active_role != Role.OPS_ADMIN:
        raise CommandError(
            "role_forbidden", 403, "Only an operations admin can change automations."
        )
    try:
        model = cmd.payload_model.model_validate(payload)
    except ValidationError as exc:
        raise _schema_error(exc) from None
    body = model.model_dump(mode="json")
    req_hash = request_hash(name, actor.user_id, actor.active_role, body)  # shared
    session.execute(select(func.pg_advisory_xact_lock(14014)))  # serialize automation writes
    ensure_seeded(session)
    existing = session.get(AutomationCommandKey, key)
    if existing is not None:
        if existing.command != name or existing.request_hash != req_hash:
            raise CommandError(
                "idempotency_key_conflict",
                409,
                "That key was already used for a different command, user, role or payload.",
            )
        existing.attempts += 1
        existing.last_at = now
        out = CommandOut(
            status="replayed",
            result=dict(existing.result or {}),
            event_ids=[str(e) for e in existing.event_ids],
        )
        session.commit()
        return out
    current = cmd.current_version(session, model)
    if expected_version != current:
        raise CommandError(
            "stale_version", 409, f"Expected version {current}. Refresh and review before retrying."
        )
    ctx = {
        "user_id": actor.user_id,
        "expected_version": expected_version,
        **body,
        **(cmd.key_context(session, model) if cmd.key_context else {}),
    }
    expected_key = cmd.key_template.format(**ctx)
    if key != expected_key:
        raise CommandError(
            "idempotency_key_mismatch", 422, f"idempotency_key must be '{expected_key}'."
        )
    done = cmd.handler(session, actor, model, now)
    event = AutomationEvent(
        type=done.event,
        at=now,
        actor_id=actor.user_id,
        actor_role=actor.active_role.value,
        record_ids=done.record_ids,
        summary=done.summary,
        detail={"command": name, "key": key},
    )
    session.add(event)
    session.flush()
    ids = [f"AEVT-{event.id}"]
    session.add(
        AutomationCommandKey(
            key=key,
            command=name,
            status="completed",
            request_id=request_id,
            request_hash=req_hash,
            attempts=1,
            first_at=now,
            last_at=now,
            result=done.result,
            event_ids=ids,
        )
    )
    session.commit()
    return CommandOut(status="recorded", result=done.result, event_ids=ids)


# ---- HTTP ---------------------------------------------------------------------------------------


class CommandIn(BaseModel):
    idempotency_key: str
    expected_version: int
    payload: dict[str, Any] = {}


class CommandOut(BaseModel):
    status: str  # recorded | replayed
    result: dict[str, Any]
    event_ids: list[str]


class WorkflowVersionOut(BaseModel):
    version: int
    graph_hash: str
    published_by: str
    reason: str
    created_at: datetime


class DraftOut(BaseModel):
    version: int
    from_version: int
    revision: int
    graph: dom.Graph
    graph_hash: str
    validation: list[dom.Violation]
    latest_check: "CheckRunOut | None"


class CheckRunOut(BaseModel):
    run_id: int
    graph_hash: str
    passed: bool
    results: list[dom.ScenarioResult]
    created_at: datetime


class PinnedCase(BaseModel):
    case_id: str
    workflow_version: int
    policy_version: int


class WorkflowOut(BaseModel):
    workflow_id: str
    name: str
    active_version: int
    graph: dom.Graph
    versions: list[WorkflowVersionOut]
    draft: DraftOut | None
    used_by: list[PinnedCase]


class SpecialistOut(BaseModel):
    specialist_id: str
    status: str
    revision: int
    fields: dict[str, Any]


class PolicyDraftOut(BaseModel):
    policy_id: str
    version: int
    from_version: int
    rules: list[Any]


class AutomationEventOut(BaseModel):
    id: str
    type: str
    at: datetime
    actor_id: str
    actor_role: str
    record_ids: list[str]
    summary: str


DraftOut.model_rebuild()


def _session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


Db = Annotated[Session, Depends(_session)]


def _actor(request: Request, session: Db) -> Actor:
    settings = request.app.state.settings
    return auth.load_actor(
        session,
        settings.secret(),
        auth.session_cookie(request.headers.getlist("cookie")),
        settings.synthetic,
    )


ActorDep = Annotated[Actor, Depends(_actor)]


def _staff(actor: Actor) -> None:
    if actor.active_role not in STAFF_ROLES or actor.active_role not in actor.roles:
        raise CommandError("role_forbidden", 403, "This role cannot read automations.")


router = APIRouter(prefix="/api/automations", tags=["automations"])


@router.post("/commands/{name}")
def run_automation_command(
    name: str, body: CommandIn, request: Request, session: Db, actor: ActorDep
) -> CommandOut:
    return execute(
        session,
        now=request.app.state.clock.now(),
        name=name,
        key=body.idempotency_key,
        expected_version=body.expected_version,
        payload=body.payload,
        actor=actor,
        request_id=request.headers.get("x-request-id") or uuid.uuid4().hex,
    )


def _check_out(run: WorkflowCheckRun) -> CheckRunOut:
    return CheckRunOut(
        run_id=run.id,
        graph_hash=run.graph_hash,
        passed=run.passed,
        results=[dom.ScenarioResult.model_validate(r) for r in run.results],
        created_at=run.created_at,
    )


@router.get("/workflows/{workflow_id}")
def get_workflow(workflow_id: str, session: Db, actor: ActorDep) -> WorkflowOut:
    _staff(actor)
    from vera_api.models import Case

    graph = active_graph(session, workflow_id)
    session.commit()  # keep the seed
    wf = session.get(WorkflowDefinition, workflow_id)
    assert wf is not None
    versions = session.scalars(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version)
    ).all()
    d = session.scalars(
        select(WorkflowDraft).where(WorkflowDraft.workflow_id == workflow_id)
    ).first()
    draft = None
    if d is not None:
        g = dom.Graph.model_validate(d.graph)
        run = session.scalars(
            select(WorkflowCheckRun)
            .where(
                WorkflowCheckRun.workflow_id == workflow_id,
                WorkflowCheckRun.draft_version == d.version,
            )
            .order_by(WorkflowCheckRun.id.desc())
        ).first()
        draft = DraftOut(
            version=d.version,
            from_version=d.from_version,
            revision=d.revision,
            graph=g,
            graph_hash=dom.graph_hash(g),
            validation=dom.validate(g),
            latest_check=_check_out(run) if run else None,
        )
    cases = session.scalars(select(Case).where(Case.live.is_(True)).order_by(Case.id)).all()
    return WorkflowOut(
        workflow_id=wf.id,
        name=wf.name,
        active_version=wf.active_version,
        graph=graph,
        versions=[
            WorkflowVersionOut(
                version=v.version,
                graph_hash=v.graph_hash,
                published_by=v.published_by,
                reason=v.reason,
                created_at=v.created_at,
            )
            for v in versions
        ],
        draft=draft,
        used_by=[
            PinnedCase(
                case_id=c.id, workflow_version=c.workflow_version, policy_version=c.policy_version
            )
            for c in cases
        ],
    )


@router.get("/specialists")
def list_specialists(session: Db, actor: ActorDep) -> list[SpecialistOut]:
    _staff(actor)
    rows = session.scalars(select(SpecialistDefinition).order_by(SpecialistDefinition.id)).all()
    return [
        SpecialistOut(specialist_id=r.id, status=r.status, revision=r.revision, fields=r.fields)
        for r in rows
    ]


@router.get("/policies/{policy_id}/drafts")
def list_policy_drafts(policy_id: str, session: Db, actor: ActorDep) -> list[PolicyDraftOut]:
    _staff(actor)
    rows = session.scalars(select(PolicyDraft).where(PolicyDraft.policy_id == policy_id)).all()
    return [
        PolicyDraftOut(
            policy_id=r.policy_id, version=r.version, from_version=r.from_version, rules=r.rules
        )
        for r in rows
    ]


@router.get("/events")
def list_events(session: Db, actor: ActorDep) -> list[AutomationEventOut]:
    _staff(actor)
    rows = session.scalars(select(AutomationEvent).order_by(AutomationEvent.id)).all()
    return [
        AutomationEventOut(
            id=f"AEVT-{r.id}",
            type=r.type,
            at=r.at,
            actor_id=r.actor_id,
            actor_role=r.actor_role,
            record_ids=[str(x) for x in r.record_ids],
            summary=r.summary,
        )
        for r in rows
    ]


plugins.register_router(router)
plugins.register_reset_tables(
    [
        "automation_events",
        "automation_command_keys",
        "policy_drafts",
        "specialist_definitions",
        "workflow_check_runs",
        "workflow_drafts",
        "workflow_versions",
        "workflow_definitions",
        # Published policy versions > 1 come only from publish_policy_version; the demo reset
        # truncates them and seed.py re-seeds v1.
        "policy_versions",
    ]
)
