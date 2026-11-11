"""Automations (VER-014): workflow graph as data, validation rules 1-9, dry-run scenarios,
command payloads. Pure: no I/O. Validation and execution read node `kind` (decision D4), never
the visual `category`."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from vera_domain.commands import Payload

WORKFLOW_ID = "card-dispute"

NodeKind = Literal[
    "trigger",
    "finance_specialist",
    "human_checkpoint",
    "policy_check",
    "communication",
    "verification",
    "decision",
    "remediation",
    "close_case",
]
Category = Literal["trigger", "agent", "policy", "checkpoint", "action"]
DEFAULT_CATEGORY: dict[str, Category] = {
    "trigger": "trigger",
    "finance_specialist": "agent",
    "communication": "agent",
    "verification": "agent",
    "policy_check": "policy",
    "human_checkpoint": "checkpoint",
    "decision": "checkpoint",
    "close_case": "checkpoint",
    "remediation": "action",
}
# Controls a money-affecting node must be preceded by on every path (rule 9, ToSpec §9.2).
REQUIRED_CONTROLS = (
    "policy_controller",
    "human_decision",
    "reviewer_approval",
    "evidence_recheck",
    "decision_record",
    "idempotency_gate",
)
CONTROL_LABELS = {
    "policy_controller": "Policy Controller",
    "human_decision": "human decision checkpoint",
    "reviewer_approval": "reviewer approval",
    "evidence_recheck": "current-evidence recheck",
    "decision_record": "decision record",
    "idempotency_gate": "idempotency gate",
}
RULES = {
    1: "Exactly one trigger",
    2: "Every step reachable from the trigger",
    3: "Every path can reach Close or monitor",
    4: "No dead ends",
    5: "Every declared decision outcome has a path",
    6: "Every analyst-started step and every action has a failure path",
    7: "Each outcome leads to exactly one step",
    8: "Every back edge has a retry limit",
    9: "Money-affecting steps keep their required controls",
}
# Approved tool library for specialists (anything else is prohibited).
APPROVED_TOOLS = frozenset(
    {"read_evidence_field", "search_transactions", "read_attachment", "draft_message"}
)


class Node(BaseModel):
    key: str
    kind: NodeKind
    label: str
    category: Category  # visual only; never read by validation or execution
    outcomes: list[str] = Field(default_factory=list)
    failure_outcomes: list[str] = Field(default_factory=list)
    analyst_started: bool = False
    money_affecting: bool = False
    parallel: bool = False  # one outcome fans out to several steps (joined downstream)
    provides: list[str] = Field(default_factory=list)  # REQUIRED_CONTROLS this node supplies
    specialist_id: str | None = None


class Edge(BaseModel):
    source: str
    target: str
    outcome: str
    max: int | None = Field(default=None, ge=1)


class Graph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]

    def node(self, key: str) -> Node | None:
        return next((n for n in self.nodes if n.key == key), None)


def graph_hash(graph: Graph) -> str:
    body = json.dumps(graph.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _n(key: str, kind: NodeKind, label: str, outcomes: list[str], **kw: Any) -> Node:
    return Node(
        key=key, kind=kind, label=label, category=DEFAULT_CATEGORY[kind], outcomes=outcomes, **kw
    )


def _e(source: str, target: str, outcome: str, mx: int | None = None) -> Edge:
    return Edge(source=source, target=target, outcome=outcome, max=mx)


# Workflow v3 (Handoff §10.3 nodes, §7.2 outcomes). The executed investigation sub-graph
# (vera_domain.investigation.INVESTIGATION_V3) is derived from this definition.
WORKFLOW_V3 = Graph(
    nodes=[
        _n("intake", "trigger", "Report received", ["received"], parallel=True),
        _n("charge_investigator", "finance_specialist", "Charge Investigator", ["done"]),
        _n(
            "related_transaction_investigator",
            "finance_specialist",
            "Related-Transaction Investigator",
            ["done"],
        ),
        _n("receipt_document_reviewer", "finance_specialist", "Evidence assessment", ["done"]),
        _n(
            "pc1",
            "policy_check",
            "Policy Controller · evidence sufficiency",
            ["sufficient", "missing evidence", "contradictory"],
        ),
        _n(
            "cardholder_follow_up",
            "communication",
            "Cardholder follow-up",
            ["sent", "send failed"],
            failure_outcomes=["send failed"],
            analyst_started=True,
        ),
        _n(
            "await_cardholder_response",
            "human_checkpoint",
            "Await cardholder response",
            ["response", "no answer"],
            failure_outcomes=["no answer"],
        ),
        _n(
            "identity_verification",
            "verification",
            "Identity verification",
            ["verified", "failed"],
            failure_outcomes=["failed"],
            analyst_started=True,
        ),
        _n(
            "live_verification",
            "verification",
            "Live verification",
            ["verified", "contradicted", "no answer"],
            failure_outcomes=["no answer"],
            analyst_started=True,
        ),
        _n(
            "decision_packet_preparer",
            "finance_specialist",
            "Prepare recommendation",
            ["prepared"],
            provides=["evidence_recheck"],
        ),
        _n(
            "analyst_decision",
            "decision",
            "Analyst decision",
            ["unauthorized", "authorized", "escalation"],
            failure_outcomes=["escalation"],
            analyst_started=True,
            provides=["human_decision", "decision_record"],
        ),
        _n(
            "pc2",
            "policy_check",
            "Policy Controller · credit eligibility",
            ["eligible", "not eligible"],
            provides=["policy_controller"],
        ),
        _n(
            "reviewer_approval",
            "human_checkpoint",
            "Reviewer approval",
            ["approved", "rejected"],
            failure_outcomes=["rejected"],
            analyst_started=True,
            provides=["reviewer_approval"],
        ),
        _n(
            "credit_executor",
            "remediation",
            "Provisional credit",
            ["issued", "timeout"],
            failure_outcomes=["timeout"],
            money_affecting=True,
            provides=["idempotency_gate"],
        ),
        _n("prevention_planner", "finance_specialist", "Prevention Planner", ["planned"]),
        _n(
            "admin_approval",
            "human_checkpoint",
            "Admin approval",
            ["approved", "declined"],
            failure_outcomes=["declined"],
            analyst_started=True,
        ),
        _n(
            "dispute_packet_preparer",
            "remediation",
            "Dispute packet",
            ["submitted", "failed"],
            failure_outcomes=["failed"],
        ),
        _n(
            "final_communication",
            "communication",
            "Final communication",
            ["delivered", "send failed"],
            failure_outcomes=["send failed"],
            analyst_started=True,
        ),
        _n(
            "retry_within_limits",
            "policy_check",
            "Retry within limits",
            ["retry", "escalation"],
            failure_outcomes=["escalation"],
        ),
        _n(
            "analyst_handoff",
            "human_checkpoint",
            "Analyst handoff",
            ["close unresolved"],
            failure_outcomes=["close unresolved"],
            analyst_started=True,
        ),
        _n("close_or_monitor", "close_case", "Close or monitor", []),
    ],
    edges=[
        _e("intake", "charge_investigator", "received"),
        _e("intake", "related_transaction_investigator", "received"),
        _e("charge_investigator", "receipt_document_reviewer", "done"),
        _e("related_transaction_investigator", "receipt_document_reviewer", "done"),
        _e("receipt_document_reviewer", "pc1", "done"),
        _e("pc1", "identity_verification", "sufficient"),
        _e("pc1", "cardholder_follow_up", "missing evidence"),
        _e("pc1", "analyst_handoff", "contradictory"),
        _e("cardholder_follow_up", "await_cardholder_response", "sent"),
        _e("cardholder_follow_up", "retry_within_limits", "send failed"),
        _e("await_cardholder_response", "receipt_document_reviewer", "response", 3),
        _e("await_cardholder_response", "retry_within_limits", "no answer"),
        _e("identity_verification", "live_verification", "verified"),
        _e("identity_verification", "analyst_handoff", "failed"),
        _e("live_verification", "decision_packet_preparer", "verified"),
        _e("live_verification", "analyst_handoff", "contradicted"),
        _e("live_verification", "retry_within_limits", "no answer"),
        _e("decision_packet_preparer", "analyst_decision", "prepared"),
        _e("analyst_decision", "pc2", "unauthorized"),
        _e("analyst_decision", "final_communication", "authorized"),
        _e("analyst_decision", "analyst_handoff", "escalation"),
        _e("pc2", "reviewer_approval", "eligible"),
        _e("pc2", "dispute_packet_preparer", "not eligible"),
        _e("reviewer_approval", "credit_executor", "approved"),
        _e("reviewer_approval", "decision_packet_preparer", "rejected", 2),
        _e("credit_executor", "prevention_planner", "issued"),
        _e("credit_executor", "retry_within_limits", "timeout"),
        _e("prevention_planner", "admin_approval", "planned"),
        _e("admin_approval", "dispute_packet_preparer", "approved"),
        _e("admin_approval", "dispute_packet_preparer", "declined"),
        _e("dispute_packet_preparer", "final_communication", "submitted"),
        _e("dispute_packet_preparer", "analyst_handoff", "failed"),
        _e("final_communication", "close_or_monitor", "delivered"),
        _e("final_communication", "retry_within_limits", "send failed"),
        _e("retry_within_limits", "cardholder_follow_up", "retry", 3),
        _e("retry_within_limits", "analyst_handoff", "escalation"),
        _e("analyst_handoff", "close_or_monitor", "close unresolved"),
    ],
)

# Executor kinds (vera_domain.investigation) for the canonical kinds it runs.
EXECUTOR_KIND = {"finance_specialist": "specialist", "policy_check": "policy_check"}


def executed_subgraph(graph: Graph, keys: list[str]) -> dict[str, Any]:
    """The executor's sub-graph, built from node kind: nodes in `keys`, edges between them,
    `__start__` for edges from the trigger, `__end__` after the last key."""
    nodes = []
    for key in keys:
        node = graph.node(key)
        if node is None:
            raise ValueError(f"{key} is not in the workflow graph")
        nodes.append({"key": key, "kind": EXECUTOR_KIND[node.kind]})
    trigger = next(n.key for n in graph.nodes if n.kind == "trigger")
    edges: list[list[str]] = []
    for e in graph.edges:
        if e.target in keys and e.source == trigger:
            edges.append(["__start__", e.target])
        elif e.source in keys and e.target in keys and e.max is None:
            edges.append([e.source, e.target])
    edges.append([keys[-1], "__end__"])
    return {"nodes": nodes, "edges": edges}


# ---- validation ---------------------------------------------------------------------------------


class Violation(BaseModel):
    rule: int
    rule_name: str
    node_ids: list[str]
    message: str


def _v(rule: int, nodes: list[str], message: str) -> Violation:
    return Violation(rule=rule, rule_name=RULES[rule], node_ids=nodes, message=message)


def _out(graph: Graph) -> dict[str, list[Edge]]:
    out: dict[str, list[Edge]] = {n.key: [] for n in graph.nodes}
    for e in graph.edges:
        out.setdefault(e.source, []).append(e)
    return out


def _reach(start: list[str], adj: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(start)
    while stack:
        k = stack.pop()
        if k in seen:
            continue
        seen.add(k)
        stack.extend(adj.get(k, []))
    return seen


def money_control_violations(graph: Graph) -> list[Violation]:
    """Rule 9: every path from the trigger to a money-affecting node passes every control."""
    keys = {n.key for n in graph.nodes}
    triggers = [n.key for n in graph.nodes if n.kind == "trigger"]
    provides = {n.key: set(n.provides) for n in graph.nodes}
    full = set(REQUIRED_CONTROLS)
    preds: dict[str, list[str]] = {k: [] for k in keys}
    for e in graph.edges:
        if e.source in keys and e.target in keys:
            preds[e.target].append(e.source)
    reach = _reach(triggers, {k: [e.target for e in v] for k, v in _out(graph).items()})
    have: dict[str, set[str]] = {k: (set() if k in triggers else set(full)) for k in keys}
    changed = True
    while changed:
        changed = False
        for k in keys:
            if k in triggers or k not in reach:
                continue
            inc = [have[p] | provides[p] for p in preds[k] if p in reach]
            new = set.intersection(*inc) if inc else set()
            if new != have[k]:
                have[k], changed = new, True
    found = []
    for n in graph.nodes:
        if n.money_affecting:
            missing = [c for c in REQUIRED_CONTROLS if c not in have[n.key] | provides[n.key]]
            if missing:
                names = ", ".join(CONTROL_LABELS[c] for c in missing)
                found.append(
                    _v(9, [n.key], f"{n.label} moves money and must be preceded by: {names}.")
                )
    return found


def validate(graph: Graph) -> list[Violation]:
    """Rules 1-9 (Handoff §7.3). Each violation names the node(s) and the rule."""
    found: list[Violation] = []
    keys = {n.key for n in graph.nodes}
    out = _out(graph)
    for e in graph.edges:
        if e.source not in keys or e.target not in keys:
            found.append(_v(4, [e.source, e.target], f"Edge {e.source} → {e.target} is broken."))
    triggers = [n.key for n in graph.nodes if n.kind == "trigger"]
    if len(triggers) != 1:
        found.append(_v(1, triggers, f"The workflow has {len(triggers)} triggers; needs one."))
    adj = {k: [e.target for e in v if e.target in keys] for k, v in out.items()}
    reach = _reach(triggers, adj)
    for n in graph.nodes:
        if n.key not in reach:
            found.append(_v(2, [n.key], f"{n.label} is not reachable from the trigger."))
    closes = [n.key for n in graph.nodes if n.kind == "close_case"]
    radj: dict[str, list[str]] = {}
    for k, targets in adj.items():
        for t in targets:
            radj.setdefault(t, []).append(k)
    can_close = _reach(closes, radj)
    for n in graph.nodes:
        if n.kind == "close_case":
            continue
        if not out.get(n.key):
            found.append(_v(4, [n.key], f"{n.label} has no outgoing path."))
        elif n.key not in can_close:
            found.append(_v(3, [n.key], f"{n.label} cannot reach Close or monitor."))
        covered = {e.outcome for e in out.get(n.key, [])}
        for o in n.outcomes:
            if o not in covered:
                found.append(_v(5, [n.key], f"{n.label}: outcome '{o}' has no path."))
        if (n.analyst_started or n.kind == "remediation") and not any(
            o in covered for o in n.failure_outcomes
        ):
            found.append(_v(6, [n.key], f"{n.label} has no failure path."))
        if not n.parallel:
            for o in sorted(covered):
                dests = {e.target for e in out[n.key] if e.outcome == o}
                if len(dests) > 1:
                    found.append(
                        _v(7, [n.key], f"{n.label}: outcome '{o}' leads to {len(dests)} steps.")
                    )
    unlimited = {k: [e for e in v if e.max is None] for k, v in out.items()}
    for e in _back_edges(graph, triggers, unlimited):
        found.append(
            _v(8, [e.source, e.target], f"Loop {e.source} → {e.target} has no retry limit.")
        )
    found.extend(money_control_violations(graph))
    return found


def _back_edges(graph: Graph, triggers: list[str], out: dict[str, list[Edge]]) -> list[Edge]:
    """Edges closing a cycle among edges without a limit: every loop needs one limited edge."""
    back: list[Edge] = []
    state: dict[str, int] = {}

    def dfs(k: str) -> None:
        state[k] = 1
        for e in out.get(k, []):
            s = state.get(e.target, 0)
            if s == 1:
                back.append(e)
            elif s == 0 and graph.node(e.target) is not None:
                dfs(e.target)
        state[k] = 2

    for t in triggers:
        dfs(t)
    return back


# ---- patches ------------------------------------------------------------------------------------


class PatchOp(BaseModel):
    op: Literal["add_node", "remove_node", "update_node", "add_edge", "remove_edge"]
    node: Node | None = None
    key: str | None = None
    changes: dict[str, Any] | None = None
    edge: Edge | None = None


class PatchError(Exception):
    def __init__(self, violations: list[Violation]) -> None:
        super().__init__(violations[0].message)
        self.violations = violations


def apply_patch(graph: Graph, ops: list[PatchOp]) -> Graph:
    """Apply ops; a patch that breaks rule 9 is rejected outright (PatchError)."""
    g = graph.model_copy(deep=True)
    for op in ops:
        if op.op == "add_node" and op.node is not None:
            g.nodes.append(op.node)
        elif op.op == "remove_node" and op.key is not None:
            g.nodes = [n for n in g.nodes if n.key != op.key]
            g.edges = [e for e in g.edges if op.key not in (e.source, e.target)]
        elif op.op == "update_node" and op.key is not None:
            g.nodes = [
                Node.model_validate({**n.model_dump(), **(op.changes or {})})
                if n.key == op.key
                else n
                for n in g.nodes
            ]
        elif op.op == "add_edge" and op.edge is not None:
            g.edges.append(op.edge)
        elif op.op == "remove_edge" and op.edge is not None:
            e0 = op.edge
            g.edges = [
                e
                for e in g.edges
                if (e.source, e.target, e.outcome) != (e0.source, e0.target, e0.outcome)
            ]
    _removed_controls(graph, g)
    return g


def _removed_controls(before: Graph, after: Graph) -> None:
    """Rule 9 at patch time: removing a required control (or a node that supplies one)
    upstream of money movement is rejected, not only at publish."""
    if not any(n.money_affecting for n in before.nodes):
        return
    removed = [n for n in before.nodes if n.provides and after.node(n.key) is None]
    violations = [
        _v(
            9,
            [n.key],
            f"{n.label} cannot be removed: money-affecting steps require "
            + ", ".join(CONTROL_LABELS[c] for c in n.provides)
            + ".",
        )
        for n in removed
    ]
    if not violations:
        violations = money_control_violations(after)
    if violations:
        raise PatchError(violations)


# ---- dry run ------------------------------------------------------------------------------------


class Scenario(BaseModel):
    name: str
    script: dict[str, list[str]]  # node -> outcome per visit (last one repeats)


SCENARIOS = [
    Scenario(
        name="Missing receipt · confirmed by callback",
        script={"pc1": ["missing evidence", "sufficient"]},
    ),
    Scenario(
        name="Cardholder recognizes it · receipt attached",
        script={"analyst_decision": ["authorized"]},
    ),
    Scenario(name="Contradictory receipt", script={"pc1": ["contradictory"]}),
    Scenario(
        name="Cardholder does not respond",
        script={
            "pc1": ["missing evidence"],
            "await_cardholder_response": ["no answer"],
            "retry_within_limits": ["retry", "retry", "escalation"],
        },
    ),
    Scenario(
        name="Unanswered callback",
        script={"live_verification": ["no answer"], "retry_within_limits": ["escalation"]},
    ),
    Scenario(name="Reviewer returns case", script={"reviewer_approval": ["rejected", "approved"]}),
]
MAX_STEPS = 200


class TraceStep(BaseModel):
    step: int
    node: str
    kind: str
    outcome: str | None


class ScenarioResult(BaseModel):
    scenario: str
    passed: bool
    last_step: str | None
    steps: int
    reason: str | None
    trace: list[TraceStep]


def run_scenario(graph: Graph, scenario: Scenario) -> ScenarioResult:
    """Deterministic walk with scripted outcomes on synthetic adapters (no model calls).
    Passes when it ends on a close_case node without exceeding any retry limit."""
    out = _out(graph)
    trigger = next((n.key for n in graph.nodes if n.kind == "trigger"), None)
    trace: list[TraceStep] = []
    visits: dict[str, int] = {}
    loops: dict[tuple[str, str, str], int] = {}
    queue = [trigger] if trigger else []
    last: str | None = None

    def fail(reason: str) -> ScenarioResult:
        return ScenarioResult(
            scenario=scenario.name,
            passed=False,
            last_step=last,
            steps=len(trace),
            reason=reason,
            trace=trace,
        )

    while queue:
        key = queue.pop(0)
        node = graph.node(key) if key else None
        if node is None:
            return fail(f"missing step {key}")
        last = key
        if len(trace) >= MAX_STEPS:
            return fail("step budget exceeded")
        if node.kind == "close_case":
            trace.append(TraceStep(step=len(trace) + 1, node=key, kind=node.kind, outcome=None))
            continue
        seq = scenario.script.get(key) or node.outcomes[:1]
        i = visits.get(key, 0)
        visits[key] = i + 1
        outcome = seq[min(i, len(seq) - 1)] if seq else None
        trace.append(TraceStep(step=len(trace) + 1, node=key, kind=node.kind, outcome=outcome))
        edges = [e for e in out.get(key, []) if e.outcome == outcome]
        if not edges:
            return fail(f"dead end at {key} on '{outcome}'")
        for e in edges:
            if e.max is not None:
                ek = (e.source, e.target, e.outcome)
                loops[ek] = loops.get(ek, 0) + 1
                if loops[ek] > e.max:
                    return fail(f"retry limit {e.max} exceeded on {e.source} → {e.target}")
            if e.target not in queue:
                queue.append(e.target)
    end = graph.node(last) if last else None
    if end is None or end.kind != "close_case":
        return fail("did not reach Close or monitor")
    return ScenarioResult(
        scenario=scenario.name,
        passed=True,
        last_step=last,
        steps=len(trace),
        reason=None,
        trace=trace,
    )


def run_checks(graph: Graph) -> list[ScenarioResult]:
    return [run_scenario(graph, s) for s in SCENARIOS]


# ---- specialists and policy ---------------------------------------------------------------------


class SpecialistFields(Payload):
    name: str = Field(min_length=3)
    purpose: str = Field(min_length=10)
    records: list[str] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    output_type: str = Field(min_length=1)
    handoff: str = Field(min_length=1)
    execution_mode: Literal["replay", "live"] = "replay"


def prohibited_tools(tools: list[str]) -> list[str]:
    return [t for t in tools if t not in APPROVED_TOOLS]


# ---- command payloads ---------------------------------------------------------------------------


class CreateWorkflowDraft(Payload):
    workflow_id: str = WORKFLOW_ID
    from_version: int = Field(ge=1)


class UpdateWorkflowDraft(Payload):
    workflow_id: str = WORKFLOW_ID
    draft_version: int = Field(ge=1)
    ops: list[PatchOp] = Field(min_length=1)


class RunWorkflowChecks(Payload):
    workflow_id: str = WORKFLOW_ID
    draft_version: int = Field(ge=1)


class PublishWorkflowVersion(Payload):
    workflow_id: str = WORKFLOW_ID
    draft_version: int = Field(ge=1)
    reason: str = Field(min_length=3)


class DiscardWorkflowDraft(Payload):
    workflow_id: str = WORKFLOW_ID
    draft_version: int = Field(ge=1)


class CreateSpecialistDraft(SpecialistFields):
    specialist_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")


class UpdateSpecialistDraft(SpecialistFields):
    specialist_id: str


class AddSpecialistToWorkflow(Payload):
    specialist_id: str
    workflow_id: str = WORKFLOW_ID
    from_version: int = Field(ge=1)
    after_node: str = "receipt_document_reviewer"


class CreatePolicyDraft(Payload):
    policy_id: str
    from_version: int = Field(ge=1)


class PublishPolicyVersion(Payload):
    policy_id: str
    draft_version: int = Field(ge=1)
    receipt_threshold: int = Field(ge=0, le=500)
    reason: str = Field(min_length=3)
