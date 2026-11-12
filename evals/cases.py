"""Evaluation cases: a contract per case, checked by deterministic evaluators.

A case lives in tests/fixtures/eval_cases/EC-NN_slug.json. It replays real commands through the
gateway (the same harness steps as evals/scenarios), then every declared expectation is checked
against persisted state and the APIs the UI reads. Nothing here asks a model whether something is
allowed: every safety verdict below is an equality or membership test on stored rows.

Contract fields (all required; a case missing one fails with a contract error):

    id, title, synthetic (must be true), categories, covers, initial_facts, source_records,
    expected_extracted_facts, evidence_references, contradictions, missing_evidence,
    expected_specialist_outputs, expected_policy, expected_workflow_state,
    allowed_next_commands, forbidden_commands, expected_audit_events, expected_final_outcome,
    steps

Global invariants run after every case whatever it declares (projection = derive_step, audit
append-only, no specialist money events, money only behind its gates, exactly-once effects, no
repeated specialist work, grounded evidence links).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evals.harness import World

ROOT = Path(__file__).resolve().parent
CASES_DIR = ROOT.parent / "tests" / "fixtures" / "eval_cases"

REQUIRED = (
    "id",
    "title",
    "synthetic",
    "categories",
    "covers",
    "initial_facts",
    "source_records",
    "expected_extracted_facts",
    "evidence_references",
    "contradictions",
    "missing_evidence",
    "expected_specialist_outputs",
    "expected_policy",
    "expected_workflow_state",
    "allowed_next_commands",
    "forbidden_commands",
    "expected_audit_events",
    "expected_final_outcome",
    "steps",
)
OPTIONAL = ("trace", "case")  # report the trace; case id other than CHG-1042
CATEGORIES = ("evidence", "workflow", "financial_safety", "reliability", "product_projection")

# Events that move money, commit to a decision or end the case, and who may cause each.
MONEY_EVENT_ROLES: dict[str, frozenset[str]] = {
    "credit.requested": frozenset({"analyst"}),
    "credit.issued": frozenset({"analyst", "system"}),
    "credit.confirmed": frozenset({"analyst", "system"}),
    "dispute.submission_requested": frozenset({"analyst"}),
    "dispute.submitted": frozenset({"analyst", "system"}),
    "controls.approved": frozenset({"card_admin"}),
    "controls.declined": frozenset({"card_admin"}),
    "controls.apply_requested": frozenset({"card_admin"}),
    "controls.applied": frozenset({"card_admin", "system"}),
    "approval.approved": frozenset({"reviewer"}),
    "approval.returned": frozenset({"reviewer"}),
    "decision.recorded": frozenset({"analyst"}),
    "final_message.sent": frozenset({"analyst"}),
    "case.closed": frozenset({"analyst", "system"}),
}


@dataclass
class Check:
    evaluator: str
    category: str
    passed: bool
    detail: str = ""
    counter: str | None = None  # which report counter a failure feeds

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "evaluator": self.evaluator,
            "category": self.category,
            "passed": self.passed,
        }
        if self.detail:
            out["detail"] = self.detail
        if self.counter:
            out["counter"] = self.counter
        return out


@dataclass
class CaseResult:
    case_id: str
    title: str
    categories: list[str]
    covers: list[str]
    status: str  # PASS | FAIL
    checks: list[Check] = field(default_factory=list)
    probes: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    first_failure: str = ""
    file: str = ""
    representative: bool = False  # the case asks for its trace in the report ("trace": true)


def load_cases(only: str | None = None) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    for path in sorted(CASES_DIR.glob("EC-*.json")):
        if only and not path.name.startswith(only):
            continue
        out.append((path, json.loads(path.read_text())))
    return out


def contract_problems(case: dict[str, Any]) -> list[str]:
    problems = [f"missing field '{k}'" for k in REQUIRED if k not in case]
    if case.get("synthetic") is not True:
        problems.append("synthetic must be true: cases use only synthetic data")
    for cat in case.get("categories", []):
        if cat not in CATEGORIES:
            problems.append(f"unknown category '{cat}'")
    return problems


# ---- reads -------------------------------------------------------------------------------------


def _register(w: World, case_id: str) -> dict[str, Any]:
    w.switch("analyst")
    r = w.client.get(f"/api/cases/{case_id}/evidence")
    assert r.status_code == 200, r.text
    return dict(r.json())


def _record(w: World, case_id: str, record_id: str, cache: dict[str, Any]) -> dict[str, Any] | None:
    if record_id not in cache:
        r = w.client.get(f"/api/cases/{case_id}/evidence/{record_id}")
        cache[record_id] = r.json() if r.status_code == 200 else None
    found: dict[str, Any] | None = cache[record_id]
    return found


def _events(w: World, case_id: str) -> list[tuple[int, str, str]]:
    rows = w.q(
        "select id, type, actor_role from audit_events where case_id=:c and id>:b order by id",
        c=case_id,
        b=w.baseline_event,
    )
    return [(int(r[0]), str(r[1]), str(r[2])) for r in rows]


def _steps_by_specialist(w: World, case_id: str) -> dict[str, dict[str, Any]]:
    """The latest step each specialist ran on this case (across all runs)."""
    runs = w.client.get(f"/api/cases/{case_id}/runs").json()
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        for s in run["steps"]:
            latest[s["specialist"]] = {**s, "run_status": run["status"]}
    return latest


def _sub(seq: list[str], want: list[str]) -> bool:
    it = iter(seq)
    return all(any(t == x for x in it) for t in want)


# ---- per-case evaluators -----------------------------------------------------------------------


def check_initial(w: World, case: dict[str, Any]) -> list[Check]:
    """Initial facts and source records, read right after the reset (before any step)."""
    cid = case.get("case", "CHG-1042")
    out: list[Check] = []
    v = w.view(cid)
    f = case["initial_facts"]
    got = {
        "case_id": v["case_id"],
        "merchant": v["transaction"]["merchant"],
        "amount_cents": v["transaction"]["amount_cents"],
        "currency": v["transaction"]["currency"],
        "card_last4": v["transaction"]["card_last4"],
        "cardholder": v["cardholder"]["name"],
        "state": v["state"],
        "step": v["step"],
    }
    reg = _register(w, cid)
    records = {r["record_id"]: r for r in reg["records"]}
    if "report" in f:
        got["report"] = (records.get("REP-1042") or {}).get("fields", {}).get("statement")
    bad = {k: (got.get(k), want) for k, want in f.items() if got.get(k) != want}
    out.append(
        Check("evidence.initial_facts", "evidence", not bad, f"mismatch {bad}" if bad else "")
    )
    src = case["source_records"]
    problems = []
    for rid, fields in src.get("records", {}).items():
        rec = records.get(rid)
        if rec is None:
            problems.append(f"{rid} not in the register")
            continue
        for k, want in fields.items():
            if rec["fields"].get(k) != want:
                problems.append(f"{rid}.{k}={rec['fields'].get(k)!r}, expected {want!r}")
    kinds = {r["kind"] for r in reg["records"]}
    for kind in src.get("absent_kinds", []):
        if kind in kinds:
            problems.append(f"a {kind} record exists but the case says it is absent")
    out.append(Check("evidence.source_records", "evidence", not problems, "; ".join(problems)))
    return out


def check_final(w: World, case: dict[str, Any]) -> list[Check]:
    cid = case.get("case", "CHG-1042")
    out: list[Check] = []
    reg = _register(w, cid)
    findings = reg["findings"]
    view = w.view(cid)

    # extracted facts: each expected fact is one stored finding with these citations
    missing = []
    for want in case["expected_extracted_facts"]:
        cites = {tuple(c) for c in want.get("cites", [])}
        ok = any(
            x["kind"] == want["kind"]
            and cites <= {(lk["record_id"], lk["field"]) for lk in x["links"]}
            and (want.get("status") is None or x["status"] == want["status"])
            and all(s in x["statement"] for s in want.get("statement_contains", []))
            for x in findings
        )
        if not ok:
            missing.append(want)
    out.append(
        Check(
            "evidence.fact_extraction",
            "evidence",
            not missing,
            f"no finding matches {missing}" if missing else f"{len(findings)} finding(s)",
        )
    )
    if "findings_count" in case["evidence_references"]:
        n = case["evidence_references"]["findings_count"]
        out.append(
            Check(
                "evidence.findings_count",
                "evidence",
                len(findings) == n,
                f"{len(findings)} finding(s), expected {n}",
            )
        )

    # evidence linkage: every finding cites a record version that holds the cited field, and
    # every conflict value equals the stored value at that version
    if case["evidence_references"].get("all_findings_cited", True):
        out.append(_linkage(w, cid, reg))

    # contradictions
    c = case["contradictions"]
    open_fields = sorted(x["field"] for x in reg["open_conflicts"])
    resolved = sorted(
        x["finding_id"] for x in findings if x["kind"] == "conflict" and x["status"] == "resolved"
    )
    problems = []
    if "open" in c and open_fields != sorted(c["open"]):
        problems.append(f"open conflicts {open_fields}, expected {sorted(c['open'])}")
    if "resolved_count" in c and len(resolved) != c["resolved_count"]:
        problems.append(f"{len(resolved)} resolved conflict(s), expected {c['resolved_count']}")
    if "resolved_by_prefix" in c:
        by = {x["resolved_by"] for x in findings if x["status"] == "resolved" and x["resolved_by"]}
        if not by or not all(str(b).startswith(c["resolved_by_prefix"]) for b in by):
            problems.append(
                f"resolved by {sorted(map(str, by))}, expected {c['resolved_by_prefix']}*"
            )
    out.append(Check("evidence.contradictions", "evidence", not problems, "; ".join(problems)))

    # missing evidence
    want_missing = case["missing_evidence"]
    out.append(
        Check(
            "evidence.missing",
            "evidence",
            reg["missing"] == want_missing,
            f"missing {reg['missing']}, expected {want_missing}",
        )
    )

    # stale evidence (optional): checks marked stale and current record versions
    st = case["evidence_references"].get("stale_checks")
    if st is not None:
        stale = sorted(x["key"] for x in reg["checks"] if x["status"] == "stale")
        out.append(
            Check(
                "evidence.stale_detection",
                "evidence",
                stale == sorted(st),
                f"stale checks {stale}, expected {sorted(st)}",
            )
        )
    for rid, ver in case["evidence_references"].get("current_versions", {}).items():
        cur = {r["record_id"]: r["current_version"] for r in reg["records"]}
        out.append(
            Check(
                f"evidence.current_version:{rid}",
                "evidence",
                cur.get(rid) == ver,
                f"{rid} at v{cur.get(rid)}, expected v{ver}",
            )
        )
    for rid, status in case["evidence_references"].get("record_status", {}).items():
        statuses = {r["record_id"]: r["status"] for r in reg["records"]}
        got_status = statuses.get(rid)
        if rid.endswith("*"):
            got_status = next((s for r, s in statuses.items() if r.startswith(rid[:-1])), None)
        out.append(
            Check(
                f"evidence.record_status:{rid}",
                "evidence",
                got_status == status,
                f"{rid} is {got_status!r}, expected {status!r}",
            )
        )

    out += _specialists(w, cid, case["expected_specialist_outputs"])

    # policy
    pol_want = case["expected_policy"]
    pol = view.get("policy")
    problems = []
    if pol_want.get("evaluated") is False:
        if pol is not None:
            problems.append(f"policy evaluated ({pol.get('status')}), expected never evaluated")
    else:
        pol = pol or {}
        for k in ("status", "code"):
            if k in pol_want and pol.get(k) != pol_want[k]:
                problems.append(f"policy.{k} {pol.get(k)!r}, expected {pol_want[k]!r}")
        for r in pol_want.get("rules_failed_include", []):
            if r not in pol.get("rules_failed", []):
                problems.append(f"rule {r} did not fail")
        for r in pol_want.get("rules_passed_include", []):
            if r not in pol.get("rules_passed", []):
                problems.append(f"rule {r} did not pass")
    out.append(
        Check(
            "financial_safety.policy_result",
            "financial_safety",
            not problems,
            "; ".join(problems),
            counter="policy_violations",
        )
    )

    # workflow state
    ws = case["expected_workflow_state"]
    got_ws = {"state": view["state"], "step": view["step"]}
    bad = {k: (got_ws.get(k), v) for k, v in ws.items() if k in got_ws and got_ws[k] != v}
    out.append(Check("workflow.state", "workflow", not bad, f"{got_ws} vs {ws}" if bad else ""))

    # allowed next commands, per role
    for role, cmds in case["allowed_next_commands"].items():
        w.switch(role)
        have = {a["command"] for a in w.view(cid)["available_actions"]}
        have |= {a["command"] for a in w.view(cid).get("recovery_actions", [])}
        lack = sorted(set(cmds) - have)
        out.append(
            Check(
                f"product_projection.actions:{role}",
                "product_projection",
                not lack,
                f"not offered to {role}: {lack} (offered {sorted(have)})" if lack else "",
            )
        )

    # forbidden commands at the final state: probed, never offered, refused, nothing written
    from evals.harness import do_probe

    for probe in case["forbidden_commands"]:
        res = do_probe(w, probe, f"[{case['id']}] final", where="final")
        out.append(
            Check(
                f"financial_safety.forbidden:{probe['as']}:{probe['command']}",
                "financial_safety",
                res["passed"],
                "; ".join(res["problems"]) or f"refused {res['http']} {res['code']}",
                counter=_probe_counter(res),
            )
        )

    out += _audit(w, cid, case["expected_audit_events"])
    out += _outcome(w, cid, case["expected_final_outcome"])
    return out


def _probe_counter(res: dict[str, Any]) -> str:
    return {
        "permission": "permission_failures",
        "stale_approval": "stale_approval_failures",
        "idempotency": "idempotency_failures",
    }.get(res["gate"], "policy_violations")


def _linkage(w: World, cid: str, reg: dict[str, Any]) -> Check:
    cache: dict[str, Any] = {}
    problems = []
    n = 0
    for x in reg["findings"]:
        if not x["links"]:
            problems.append(f"{x['finding_id']} cites nothing")
        for lk in x["links"]:
            n += 1
            rec = _record(w, cid, lk["record_id"], cache)
            if rec is None:
                problems.append(f"{x['finding_id']} cites unknown record {lk['record_id']}")
                continue
            ver = next((v for v in rec["versions"] if v["version"] == lk["version"]), None)
            if ver is None or lk["field"] not in ver["fields"]:
                problems.append(
                    f"{x['finding_id']} cites {lk['record_id']}@{lk['version']}."
                    f"{lk['field']} which does not exist"
                )
    for cf in reg["open_conflicts"]:
        for val in cf["values"]:
            rec = _record(w, cid, val["record_id"], cache)
            vers = {v["version"]: v["fields"] for v in (rec or {}).get("versions", [])}
            stored = vers.get(val["version"], {})
            if val["value"] not in stored.values():
                problems.append(
                    f"conflict value {val['value']!r} not stored on "
                    f"{val['record_id']}@{val['version']}"
                )
    return Check(
        "evidence.source_linkage",
        "evidence",
        not problems,
        "; ".join(problems) or f"{n} citation(s) resolve to stored fields",
        counter="unsupported_claims",
    )


def _specialists(w: World, cid: str, spec: dict[str, Any]) -> list[Check]:
    out: list[Check] = []
    steps = _steps_by_specialist(w, cid)
    reg = _register(w, cid)
    for name, want in spec.items():
        if name.startswith("_"):
            continue
        s = steps.get(name)
        if want is None:
            out.append(
                Check(
                    f"workflow.specialist:{name}",
                    "workflow",
                    s is None,
                    f"{name} ran ({s and s['status']}) but the case says it must not",
                )
            )
            continue
        problems = []
        if s is None:
            problems.append("never ran")
        else:
            for k in ("status", "failure_reason", "execution_mode", "replayed"):
                if k in want and s.get(k) != want[k]:
                    problems.append(f"{k} {s.get(k)!r}, expected {want[k]!r}")
            if "attempts" in want and s.get("attempts") != want["attempts"]:
                problems.append(f"attempts {s.get('attempts')}, expected {want['attempts']}")
        if "findings" in want:
            n = sum(1 for f in reg["findings"] if f"-{name}-" in f["finding_id"])
            if n != want["findings"]:
                problems.append(f"{n} finding(s), expected {want['findings']}")
        out.append(
            Check(f"workflow.specialist:{name}", "workflow", not problems, "; ".join(problems))
        )
    if "_verification" in spec:
        out.append(_verification(w, cid, spec["_verification"]))
    if "_follow_up" in spec:
        out.append(_follow_up(w, cid, spec["_follow_up"]))
    if "_response_review" in spec:
        comms = w.client.get(f"/api/cases/{cid}/communications").json()
        got = comms[0]["response_review"] if comms else None
        out.append(
            Check(
                "product_projection.response_review",
                "product_projection",
                got == spec["_response_review"],
                f"response_review {got!r}, expected {spec['_response_review']!r}",
            )
        )
    if "_packet" in spec:
        pkt = w.client.get(f"/api/cases/{cid}/decision-packet").json()
        want = spec["_packet"]
        problems = []
        if "status" in want and pkt.get("packet_status") != want["status"]:
            problems.append(f"packet {pkt.get('packet_status')!r}, expected {want['status']!r}")
        stmts = pkt.get("statements", [])
        if want.get("all_statements_cited") and any(not s.get("citations") for s in stmts):
            problems.append("a packet statement has no citation")
        out.append(
            Check(
                "evidence.packet_citations",
                "evidence",
                not problems,
                "; ".join(problems) or f"{len(stmts)} cited statement(s)",
                counter="unsupported_claims",
            )
        )
    return out


def _verification(w: World, cid: str, want: dict[str, Any]) -> Check:
    rows = w.client.get(f"/api/cases/{cid}/callbacks").json()
    problems = []
    if "attempts" in want and len(rows) != want["attempts"]:
        problems.append(f"{len(rows)} call attempt(s), expected {want['attempts']}")
    if rows:
        last = w.client.get(f"/api/cases/{cid}/callbacks/{rows[-1]['id']}").json()
        if "status" in want and last["status"] != want["status"]:
            problems.append(f"call status {last['status']!r}, expected {want['status']!r}")
        res = last.get("result") or {}
        if (
            "authorization_answer" in want
            and res.get("authorization_answer") != want["authorization_answer"]
        ):
            problems.append(f"authorization {res.get('authorization_answer')!r}")
        lines = {line["seq"]: line["text"] for line in last.get("transcript", [])}
        if want.get("answers_quote_transcript"):
            for a in res.get("answers", []):
                if a.get("line_seq") not in lines:
                    problems.append(f"answer {a.get('question_id')} cites no transcript line")
        if "transcript_lines" in want and len(lines) != want["transcript_lines"]:
            problems.append(f"{len(lines)} transcript line(s), expected {want['transcript_lines']}")
        if "structured_answers" in want:
            got = (last.get("voice") or {}).get("structured_answers")
            if got != want["structured_answers"]:
                problems.append(f"structured answers {got!r}")
    elif want.get("attempts", 0):
        problems.append("no call recorded")
    return Check(
        "product_projection.verification_record",
        "product_projection",
        not problems,
        "; ".join(problems),
    )


def _follow_up(w: World, cid: str, want: dict[str, Any]) -> Check:
    comms = w.client.get(f"/api/cases/{cid}/communications").json()
    problems = []
    if not comms:
        return Check("evidence.follow_up_questions", "evidence", False, "no communication")
    d = w.client.get(f"/api/cases/{cid}/communications/{comms[0]['id']}").json()
    qs = d.get("questions", [])
    if "max_questions" in want and len(qs) > want["max_questions"]:
        problems.append(f"{len(qs)} questions, at most {want['max_questions']} needed")
    text = json.dumps(qs).lower()
    for word in want.get("asks_about", []):
        if word.lower() not in text:
            problems.append(f"does not ask about {word!r}")
    for word in want.get("never_asks_about", []):
        if word.lower() in text:
            problems.append(f"asks about already-supported item {word!r}")
    if "status" in want and d.get("status") != want["status"]:
        problems.append(f"status {d.get('status')!r}, expected {want['status']!r}")
    return Check(
        "evidence.follow_up_questions",
        "evidence",
        not problems,
        "; ".join(problems) or f"{len(qs)} targeted question(s)",
    )


def _audit(w: World, cid: str, want: dict[str, Any]) -> list[Check]:
    ev = _events(w, cid)
    types = [t for _, t, _ in ev]
    problems = []
    if "subsequence" in want and not _sub(types, want["subsequence"]):
        problems.append(f"{want['subsequence']} not in order in the trail")
    for t in want.get("absent", []):
        if t in types:
            problems.append(f"unexpected {t}")
    counts = Counter(types)
    for t, n in want.get("counts", {}).items():
        if counts.get(t, 0) != n:
            problems.append(f"{counts.get(t, 0)} x {t}, expected {n}")
    for t, role in want.get("actors", {}).items():
        roles = sorted({r for _, tt, r in ev if tt == t})
        if roles != [role]:
            problems.append(f"{t} by {roles}, expected [{role!r}]")
    return [Check("reliability.audit_events", "reliability", not problems, "; ".join(problems))]


def _outcome(w: World, cid: str, want: dict[str, Any]) -> list[Check]:
    w.switch("analyst")
    v = w.view(cid)
    problems = []
    for k in ("state", "step"):
        if k in want and v[k] != want[k]:
            problems.append(f"{k} {v[k]!r}, expected {want[k]!r}")
    imp = v["charge_impact"]
    for k in ("temporary_credit_cents", "net_exposure_cents"):
        if k in want and imp[k] != want[k]:
            problems.append(f"{k} {imp[k]}, expected {want[k]}")
    if "executions" in want:
        rows = w.client.get(f"/api/cases/{cid}/executions").json()["executions"]
        got: dict[str, dict[str, int]] = {}
        for e in rows:
            got.setdefault(f"{e['adapter']}.{e['operation']}", Counter())[e["status"]] += 1
        for name, statuses in want["executions"].items():
            have = dict(got.get(name, {}))
            if have != statuses:
                problems.append(f"executions {name} {have}, expected {statuses}")
    if "approval" in want:
        rows = w.q("select status from approvals where case_id=:c order by id", c=cid)
        got_a = [r[0] for r in rows]
        if got_a != want["approval"]:
            problems.append(f"approvals {got_a}, expected {want['approval']}")
    if "decision" in want:
        rows = w.q("select decision from decisions where case_id=:c order by id", c=cid)
        got_d = rows[-1][0] if rows else None
        if got_d != want["decision"]:
            problems.append(f"decision {got_d!r}, expected {want['decision']!r}")
    if "version_unchanged_since" in want:
        snap = w.snapshots.get(want["version_unchanged_since"])
        if snap is not None and w.counts() != snap:
            problems.append("rows were written after the snapshot")
    return [
        Check(
            "product_projection.final_outcome",
            "product_projection",
            not problems,
            "; ".join(problems),
        )
    ]


# ---- global invariants (every case) ------------------------------------------------------------


def invariants(w: World, cid: str = "CHG-1042") -> list[Check]:
    return [
        _projection(w),
        _append_only(w),
        _specialist_no_money(w, cid),
        _money_roles(w, cid),
        _credit_gates(w, cid),
        _dispute_gates(w, cid),
        _controls_gates(w, cid),
        _closure_gates(w, cid),
        _exactly_once(w, cid),
        _no_repeated_work(w, cid),
    ]


def _projection(w: World) -> Check:
    """Stored state/step equals derive_step(facts) for every live case; the case version equals
    its transition count; the view shows exactly the stored state."""
    from sqlalchemy import select
    from vera_api.gateway import facts_for
    from vera_api.models import Case
    from vera_domain.facts import derive_step

    problems = []
    with w.factory() as s:
        for case in s.scalars(select(Case).where(Case.live.is_(True))):
            state, step = derive_step(facts_for(s, case))
            if (state.value, step.value) != (case.state, case.step):
                problems.append(
                    f"{case.id} stored {case.state}/{case.step}, derived {state}/{step}"
                )
            n = w.q("select count(*) from state_transitions where case_id=:c", c=case.id)[0][0]
            if n != case.case_version:
                problems.append(f"{case.id} version {case.case_version} but {n} transitions")
            last = w.q(
                "select next_state, next_step from state_transitions where case_id=:c "
                "order by id desc limit 1",
                c=case.id,
            )
            if last and tuple(last[0]) != (case.state, case.step):
                problems.append(f"{case.id} last transition {tuple(last[0])} != stored")
            w.switch("analyst")
            view = w.view(case.id)
            if (view["state"], view["step"]) != (case.state, case.step):
                problems.append(f"{case.id} view {view['state']}/{view['step']} != stored")
        s.rollback()
    return Check(
        "product_projection.derived_state", "product_projection", not problems, "; ".join(problems)
    )


def _append_only(w: World) -> Check:
    """UPDATE and DELETE on the audit trail and transitions are refused by the database."""
    from sqlalchemy import text

    problems = []
    for table in ("audit_events", "state_transitions"):
        for sql in (
            f"update {table} set id=id where id=(select max(id) from {table})",
            f"delete from {table} where id=(select max(id) from {table})",
        ):
            with w.engine.connect() as conn:
                tx = conn.begin()
                try:
                    conn.execute(text(sql))
                    problems.append(f"{sql.split()[0]} on {table} was allowed")
                except Exception:  # the append-only trigger refused it
                    pass
                finally:
                    tx.rollback()
    return Check("reliability.audit_append_only", "reliability", not problems, "; ".join(problems))


def _specialist_no_money(w: World, cid: str) -> Check:
    bad = [t for _, t, r in _events(w, cid) if r == "specialist" and t in MONEY_EVENT_ROLES]
    return Check(
        "financial_safety.specialist_no_mutation",
        "financial_safety",
        not bad,
        f"specialist caused {bad}" if bad else "",
        counter="policy_violations",
    )


def _money_roles(w: World, cid: str) -> Check:
    bad = [
        f"{t} by {r}"
        for _, t, r in _events(w, cid)
        if t in MONEY_EVENT_ROLES and r not in MONEY_EVENT_ROLES[t]
    ]
    return Check(
        "financial_safety.role_bound_effects",
        "financial_safety",
        not bad,
        "; ".join(bad),
        counter="permission_failures",
    )


def _norm(h: str | None) -> str:
    return (h or "").removeprefix("sha256:")


def _credit_gates(w: World, cid: str) -> Check:
    """Every credit is backed by a reviewer approval bound to the snapshot, policy version and
    workflow version the case had when the credit command ran, under an eligible policy."""
    problems = []
    for eid, t, _ in _events(w, cid):
        if t not in ("credit.issued", "credit.confirmed"):
            continue
        tr = w.q(
            "select evidence_snapshot, policy_version, workflow_version from state_transitions "
            "where case_id=:c and event_id<=:e order by id desc limit 1",
            c=cid,
            e=eid,
        )
        if not tr:
            problems.append(f"{t} with no transition")
            continue
        snap, pv, wv = tr[0]
        approved = w.q(
            "select snapshot_hash, policy_version, workflow_version, decided_by from approvals "
            "where case_id=:c and status in ('approved','consumed') "
            "or (case_id=:c and consumed_at is not null)",
            c=cid,
        )
        bound = [a for a in approved if (_norm(a[0]), a[1], a[2]) == (_norm(snap), pv, wv)]
        if not bound:
            problems.append(f"{t} without an approval bound to {_norm(snap)[:12]} v{pv}/v{wv}")
        reviewers = w.q(
            "select 1 from user_roles where user_id=:u and role='reviewer'",
            u=bound[0][3] if bound else "",
        )
        if bound and not reviewers:
            problems.append(f"{t} approved by a non-reviewer")
        eligible = w.q(
            "select 1 from policy_evaluations where case_id=:c and status='eligible' "
            "and replace(snapshot_hash,'sha256:','')=:h and policy_version=:p",
            c=cid,
            h=_norm(snap),
            p=pv,
        )
        if not eligible:
            problems.append(f"{t} without an eligible policy result on that snapshot")
    return Check(
        "financial_safety.credit_requires_bound_approval",
        "financial_safety",
        not problems,
        "; ".join(problems),
        counter="stale_approval_failures",
    )


def _before(types: list[str], i: int, needed: list[str]) -> list[str]:
    return [n for n in needed if n not in types[:i]]


def _dispute_gates(w: World, cid: str) -> Check:
    types = [t for _, t, _ in _events(w, cid)]
    problems = []
    for i, t in enumerate(types):
        if t == "dispute.submitted":
            lack = _before(
                types,
                i,
                ["decision.recorded", "dispute.prepared", "dispute.opened", "dispute.reviewed"],
            )
            if lack:
                problems.append(f"dispute submitted before {lack}")
    return Check(
        "financial_safety.dispute_requires_packet",
        "financial_safety",
        not problems,
        "; ".join(problems),
        counter="policy_violations",
    )


def _controls_gates(w: World, cid: str) -> Check:
    ev = _events(w, cid)
    problems = []
    for i, (_, t, _) in enumerate(ev):
        if t == "controls.applied":
            approvers = [r for _, tt, r in ev[:i] if tt == "controls.approved"]
            if not approvers or any(r != "card_admin" for r in approvers):
                problems.append(f"controls applied without a card-admin approval ({approvers})")
    return Check(
        "financial_safety.controls_require_card_admin",
        "financial_safety",
        not problems,
        "; ".join(problems),
        counter="permission_failures",
    )


def _closure_gates(w: World, cid: str) -> Check:
    types = [t for _, t, _ in _events(w, cid)]
    problems = []
    for i, t in enumerate(types):
        if t != "case.closed":
            continue
        need = ["decision.recorded", "final_message.sent"]
        if "credit.issued" in types[:i] or "credit.confirmed" in types[:i]:
            need.append("dispute.submitted")
            if not any(
                x in types[:i]
                for x in ("controls.applied", "controls.skipped", "controls.declined")
            ):
                problems.append("closed with the card-controls decision still open")
        lack = _before(types, i, need)
        if lack:
            problems.append(f"closed before {lack}")
    return Check(
        "financial_safety.closure_requires_complete_work",
        "financial_safety",
        not problems,
        "; ".join(problems),
        counter="policy_violations",
    )


def _exactly_once(w: World, cid: str) -> Check:
    types = Counter(t for _, t, _ in _events(w, cid))
    problems = []
    for t in ("credit.issued", "dispute.submitted", "controls.applied", "final_message.sent"):
        if types.get(t, 0) > 1:
            problems.append(f"{types[t]} x {t}")
    approvals = w.q("select count(*) from approvals where case_id=:c", c=cid)[0][0]
    if types.get("approval.approved", 0) > approvals:
        problems.append(
            f"{types['approval.approved']} approvals recorded for {approvals} request(s)"
        )
    # Closing twice is legitimate only as two phases: the analyst closes into dispute
    # monitoring, then the dispute outcome closes it for good (system).
    closes = Counter(r for _, t, r in _events(w, cid) if t == "case.closed")
    problems += [f"{n} x case.closed by {r}" for r, n in closes.items() if n > 1]
    if types.get("credit.issued", 0) + types.get("credit.confirmed", 0) > 1:
        problems.append("credit recorded more than once")
    rows = w.q(
        "select adapter, operation, count(*) from adapter_executions where case_id=:c "
        "and status='succeeded' and adapter in ('credit','dispute','card_controls') "
        "group by 1,2 having count(*)>1",
        c=cid,
    )
    problems += [f"{r[2]} succeeded {r[0]}.{r[1]} executions" for r in rows]
    return Check(
        "reliability.exactly_once_effects",
        "reliability",
        not problems,
        "; ".join(problems),
        counter="idempotency_failures",
    )


def _no_repeated_work(w: World, cid: str) -> Check:
    """A specialist step succeeds at most once per run: a resumed or re-delivered job never
    repeats a completed step."""
    runs = w.q(
        "select s.step_key, count(distinct s.run_id) from workflow_steps s "
        "join workflow_runs r on r.id=s.run_id where r.case_id=:c group by 1",
        c=cid,
    )
    per_run = {str(k): int(n) for k, n in runs}
    done = w.q(
        "select detail->>'step_key', count(*) from audit_events where case_id=:c and id>:b "
        "and type='run.step_succeeded' group by 1",
        c=cid,
        b=w.baseline_event,
    )
    problems = [
        f"{k} succeeded {n}x across {per_run.get(str(k), 0)} run(s)"
        for k, n in done
        if n > per_run.get(str(k), 0)
    ]
    return Check(
        "workflow.no_duplicate_work",
        "workflow",
        not problems,
        "; ".join(problems),
        counter="recovery_failures",
    )


# ---- running -----------------------------------------------------------------------------------


def run_case(
    w: World,
    path: Path,
    case: dict[str, Any],
    prepare: Callable[[World], None] | None = None,
) -> CaseResult:
    """Run one case on a freshly reset database. `prepare` (sensitivity runs only) applies a
    deliberate defect after the reset; the restore in `finally` removes it."""
    from evals.harness import ScenarioFailure, play

    res = CaseResult(
        case_id=str(case.get("id", path.stem)),
        title=str(case.get("title", path.stem)),
        categories=list(case.get("categories", [])),
        covers=list(case.get("covers", [])),
        status="PASS",
        file=str(path.relative_to(ROOT.parent)),
        representative=bool(case.get("trace")),
    )
    problems = contract_problems(case)
    if problems:
        res.checks.append(Check("contract", "workflow", False, "; ".join(problems)))
        res.status, res.first_failure = "FAIL", "contract: " + "; ".join(problems)
        return res
    cid = case.get("case", "CHG-1042")
    w.reset()
    if prepare is not None:
        prepare(w)
    try:
        res.checks += check_initial(w, case)
        try:
            play(w, res.case_id, case["steps"], cid)
            res.checks.append(
                Check("workflow.steps", "workflow", True, f"{len(case['steps'])} step(s) replayed")
            )
        except ScenarioFailure as exc:
            res.checks.append(
                Check("workflow.steps", "workflow", False, str(exc), counter=_step_counter(case))
            )
        res.checks += check_final(w, case)
        res.checks += invariants(w, cid)
    except Exception as exc:  # an evaluator crash is a failure, never a pass
        res.checks.append(Check("harness", "workflow", False, f"{type(exc).__name__}: {exc}"))
    finally:
        res.probes = list(w.probes)
        res.trace = list(w.trace)
        res.events = [f"{t} ({r})" for _, t, r in _events(w, cid)]
        w.restore()
    failed = [c for c in res.checks if not c.passed]
    if failed:
        res.status = "FAIL"
        res.first_failure = f"{failed[0].evaluator}: {failed[0].detail}"
    return res


def _step_counter(case: dict[str, Any]) -> str | None:
    covers = set(case.get("covers", []))
    if covers & {
        "worker_timeout",
        "worker_retry_partial",
        "provider_unknown_reconcile",
        "verification_provider_failure",
    }:
        return "recovery_failures"
    if covers & {"duplicate_command", "duplicate_webhook"}:
        return "idempotency_failures"
    return None
