"""Evaluation report: artifacts/eval-report.json and artifacts/eval-report.md.

Built only from what the run observed. Nothing is filled in by hand: a counter is the number of
failed checks or probes that feed it, and coverage lists the cases that declare and pass it.
The JSON holds no timestamps, run ids or random identifiers, so two runs on the same commit
produce the same file.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evals.cases import CATEGORIES, CaseResult

COMMAND = "uv run python -m evals.harness"

# The behaviours the suite must cover (one slug per required scenario).
REQUIRED_COVERAGE: dict[str, str] = {
    "missing_receipt": "Missing receipt",
    "po_amount_mismatch": "Purchase-order amount mismatch",
    "one_approved_two_delivered": "One unit approved, two units delivered",
    "cardholder_confirms": "Cardholder confirms the charge",
    "cardholder_denies": "Cardholder denies the charge",
    "ambiguous_reply": "Ambiguous cardholder reply",
    "no_reply": "No cardholder reply",
    "related_transaction": "Related transaction discovered",
    "duplicate_transaction": "Duplicate transaction",
    "verification_approved": "Verification approved",
    "verification_declined": "Verification declined",
    "verification_provider_failure": "Verification provider failure",
    "contradictory_verification": "Contradictory verification answers",
    "stale_evidence_new_reply": "Stale evidence after a new reply",
    "stale_reviewer_approval": "Stale reviewer approval",
    "reviewer_approves_credit": "Reviewer approves credit",
    "reviewer_rejects_credit": "Reviewer rejects credit",
    "card_admin_approves_controls": "Card admin approves controls",
    "card_admin_declines_controls": "Card admin declines controls",
    "duplicate_webhook": "Duplicate webhook",
    "delayed_webhook": "Delayed webhook",
    "out_of_order_events": "Out-of-order events",
    "worker_timeout": "Worker timeout",
    "worker_retry_partial": "Worker retry after partial completion",
    "provider_unknown_reconcile": "Unknown provider result requiring reconciliation",
    "unauthorized_analyst_command": "Unauthorized analyst command",
    "cardholder_analyst_action": "Cardholder attempting an analyst action",
    "reviewer_card_admin_action": "Reviewer attempting a card-admin action",
    "credit_while_policy_blocked": "Credit attempted while policy is blocked",
    "closure_with_incomplete_work": "Closure attempted with required work incomplete",
    "published_workflow_mutation": "Published workflow mutation attempt",
    "invalid_attachment_type": "Invalid attachment type",
    "oversized_attachment": "Oversized attachment",
    "duplicate_command": "Duplicate command with the same idempotency key",
    "complete_successful_investigation": "Complete successful investigation",
    "rejection_or_unresolved": "Complete investigation that ends in rejection or unresolved",
}

COUNTERS = (
    "policy_violations",
    "permission_failures",
    "unsupported_claims",
    "stale_approval_failures",
    "idempotency_failures",
    "recovery_failures",
)

PROBE_COUNTER = {
    "permission": "permission_failures",
    "stale_approval": "stale_approval_failures",
    "idempotency": "idempotency_failures",
}

KNOWN_LIMITATIONS = [
    "All cases run on the single synthetic seed (CHG-1042 and its related records). Variation "
    "comes from commands, demo seams (material change, adapter faults, call outcomes, deadline "
    "watcher) and scripted specialist turns, not from a corpus of distinct customers.",
    "Specialists run in REPLAY from reference recordings. A case that needs the model to say "
    "something else (a voicemail, a contradicted call) overrides that turn with an "
    "'eval-scripted' recording; it still passes through the same loop and validators. Live "
    "model quality is not measured by this suite.",
    "Where a stale approval moves the case to decision_pending/stale, a credit attempt is "
    "refused by the step gate first; the approval-binding gate behind it is exercised directly "
    "in tests/integration/test_decisions.py.",
    "A 'dispute' decision goes straight to the dispute track without reviewer approval; the "
    "dispute is gated by the analyst-reviewed packet. This is the product's current rule and "
    "is recorded, not changed, by this suite.",
    "Webhook cases use the ElevenLabs provider over an in-process mock transport with real "
    "signatures; no telephony provider is contacted.",
    "The worker is driven in-process with a synthetic clock (2031-01-01 onward); real "
    "concurrency between worker processes is covered by tests/integration/test_worker_graph.py.",
    "The optional LLM judge scores only bounded qualitative text and never runs in CI; it needs "
    "NVIDIA_API_KEY and --judge.",
]

REPRODUCE = [
    "infra/dev-db.sh start",
    "uv sync",
    "uv run alembic upgrade head",
    COMMAND,
    f"{COMMAND} --suite cases --only EC-01   # one case, no report written",
    "uv run pytest -q tests/evals",
]


def build(
    cases: list[CaseResult],
    scenarios: list[Any],
    baseline: dict[str, Any] | None,
    judge: dict[str, Any] | None,
    sensitivity: dict[str, Any] | None = None,
    permissions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counters: Counter[str] = Counter({c: 0 for c in COUNTERS})
    fail_by_cat: Counter[str] = Counter({c: 0 for c in CATEGORIES})
    cases_by_cat: dict[str, dict[str, int]] = {c: {"total": 0, "passed": 0} for c in CATEGORIES}
    probes_by_gate: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "refused": 0})
    for r in cases:
        for cat in r.categories:
            cases_by_cat[cat]["total"] += 1
            cases_by_cat[cat]["passed"] += r.status == "PASS"
        for chk in r.checks:
            if chk.passed:
                continue
            fail_by_cat[chk.category] += 1
            if chk.counter and not chk.evaluator.startswith("financial_safety.forbidden:"):
                counters[chk.counter] += 1
        for p in r.probes:
            probes_by_gate[p["gate"]]["total"] += 1
            probes_by_gate[p["gate"]]["refused"] += p["passed"]
            if not p["passed"]:
                counters[PROBE_COUNTER.get(p["gate"], "policy_violations")] += 1
    if permissions and permissions.get("status") == "ran":
        counters["permission_failures"] += len(permissions["failures"])
    coverage = {
        slug: {
            "label": label,
            "cases": sorted(r.case_id for r in cases if slug in r.covers),
            "passing": sorted(r.case_id for r in cases if slug in r.covers and r.status == "PASS"),
        }
        for slug, label in REQUIRED_COVERAGE.items()
    }
    uncovered = [s for s, v in coverage.items() if not v["passing"]]
    sc = Counter(s.status for s in scenarios)
    checks = [c for r in cases for c in r.checks]
    return {
        "suite": "vera-evaluation",
        "data": "synthetic (CHG-1042 · Northstar Equipment · $2,840.00); no customer records",
        "command": COMMAND,
        "summary": {
            "total_cases": len(cases),
            "passed_cases": sum(r.status == "PASS" for r in cases),
            "failed_cases": sum(r.status == "FAIL" for r in cases),
            "total_checks": len(checks),
            "failed_checks": sum(not c.passed for c in checks),
            "forbidden_command_probes": sum(v["total"] for v in probes_by_gate.values()),
            "probes_refused_without_writes": sum(v["refused"] for v in probes_by_gate.values()),
            "permission_matrix": (
                {k: permissions[k] for k in ("commands", "pairs", "refused")}
                if permissions and permissions.get("status") == "ran"
                else "not run"
            ),
            "required_behaviours": len(REQUIRED_COVERAGE),
            "required_behaviours_uncovered": uncovered,
            "regression_scenarios": {
                "passed": sc.get("PASS", 0),
                "failed": sc.get("FAIL", 0),
                "pending": sc.get("SKIPPED", 0),
            },
        },
        "counters": dict(counters),
        "failures_by_category": dict(fail_by_cat),
        "cases_by_category": cases_by_cat,
        "probes_by_gate": {k: probes_by_gate[k] for k in sorted(probes_by_gate)},
        "coverage": coverage,
        "cases": [
            {
                "id": r.case_id,
                "title": r.title,
                "status": r.status,
                "file": r.file,
                "categories": r.categories,
                "covers": r.covers,
                "checks": len(r.checks),
                "failed_checks": [c.as_dict() for c in r.checks if not c.passed],
                "probes": len(r.probes),
            }
            for r in cases
        ],
        "failed_scenarios": [
            {"scenario": s.scenario, "detail": s.detail} for s in scenarios if s.status == "FAIL"
        ],
        "representative_traces": [
            {
                "case": r.case_id,
                "title": r.title,
                "commands": r.trace,
                "audit_events": canonical_events(r.events),
            }
            for r in cases
            if r.representative
        ],
        "permission_matrix": permissions or {"status": "not run"},
        "evaluator_sensitivity": sensitivity or {"status": "not run"},
        "baseline": baseline or {"status": "not run"},
        "llm_judge": judge or {"status": "not run", "reason": "pass --judge with NVIDIA_API_KEY"},
        "known_limitations": KNOWN_LIMITATIONS,
        "reproduce": REPRODUCE,
    }


def canonical_events(events: list[str]) -> list[str]:
    """The trail with each contiguous block of specialist events sorted. The investigation
    graph runs two specialists in parallel, so their events interleave differently from run to
    run; sorting inside the block keeps the report byte-stable without hiding any event."""
    out: list[str] = []
    block: list[str] = []
    for e in events:
        if e.endswith("(specialist)"):
            block.append(e)
            continue
        out += sorted(block)
        block = []
        out.append(e)
    return out + sorted(block)


def write(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "eval-report.json"
    m = out_dir / "eval-report.md"
    j.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n")
    m.write_text(markdown(report))
    return j, m


def _matrix_row(m: Any) -> str:
    if not isinstance(m, dict):
        return "| Permission matrix (every command x every role without it) | not run |"
    return (
        f"| Permission matrix (every command x every role without it) | {m['refused']} of "
        f"{m['pairs']} pairs refused with 403, nothing written ({m['commands']} commands) |"
    )


def _yes(n: int) -> str:
    return "0" if n == 0 else f"**{n}**"


def markdown(r: dict[str, Any]) -> str:
    s = r["summary"]
    lines = [
        "# Vera evaluation report",
        "",
        f"Generated by `{r['command']}`. Data: {r['data']}.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Evaluation cases | {s['total_cases']} |",
        f"| Passed | {s['passed_cases']} |",
        f"| Failed | {s['failed_cases']} |",
        f"| Deterministic checks | {s['total_checks']} ({s['failed_checks']} failed) |",
        f"| Forbidden-command probes | {s['forbidden_command_probes']} "
        f"({s['probes_refused_without_writes']} refused with nothing written) |",
        _matrix_row(s["permission_matrix"]),
        f"| Required behaviours covered | {s['required_behaviours'] - len(s['required_behaviours_uncovered'])}"  # noqa: E501
        f" / {s['required_behaviours']} |",
        f"| Regression scenarios (evals/scenarios) | {s['regression_scenarios']['passed']} passed,"
        f" {s['regression_scenarios']['failed']} failed,"
        f" {s['regression_scenarios']['pending']} pending |",
        "",
        "## Safety counters",
        "",
        "Each counter is the number of failed checks or probes of that kind. Zero is the target.",
        "",
        "| Counter | Count |",
        "|---|---|",
    ]
    lines += [f"| {k.replace('_', ' ')} | {_yes(v)} |" for k, v in r["counters"].items()]
    lines += [
        "",
        "## Failures by category",
        "",
        "| Category | Cases (passed / total) | Failed checks |",
        "|---|---|---|",
    ]
    for cat, n in r["failures_by_category"].items():
        cb = r["cases_by_category"][cat]
        lines.append(f"| {cat} | {cb['passed']} / {cb['total']} | {_yes(n)} |")
    lines += [
        "",
        "## Forbidden-command probes by gate",
        "",
        "A probe posts a command that must not run. It passes only if the command is not offered,",
        "the gateway refuses it with the expected gate, and no row is written.",
        "",
        "| Gate | Probes | Refused correctly |",
        "|---|---|---|",
    ]
    lines += [f"| {g} | {v['total']} | {v['refused']} |" for g, v in r["probes_by_gate"].items()]
    lines += ["", "## Cases", "", "| Case | Result | Checks | Probes | Title |"]
    lines.append("|---|---|---|---|---|")
    for c in r["cases"]:
        res = "PASS" if c["status"] == "PASS" else "**FAIL**"
        lines.append(f"| {c['id']} | {res} | {c['checks']} | {c['probes']} | {c['title']} |")
    failed = [c for c in r["cases"] if c["failed_checks"]]
    if failed:
        lines += ["", "### Failed checks", ""]
        for c in failed:
            for f in c["failed_checks"]:
                lines.append(f"- {c['id']} `{f['evaluator']}`: {f.get('detail', '')}")
    if r["failed_scenarios"]:
        lines += ["", "### Failed regression scenarios", ""]
        lines += [f"- {x['scenario']}: {x['detail']}" for x in r["failed_scenarios"]]
    lines += ["", "## Coverage of required behaviours", "", "| Behaviour | Cases |", "|---|---|"]
    for v in r["coverage"].values():
        cases = ", ".join(v["passing"]) or "**not covered**"
        lines.append(f"| {v['label']} | {cases} |")
    lines += ["", "## Evaluator sensitivity", ""]
    sens = r["evaluator_sensitivity"]
    if sens.get("status") != "ran":
        lines.append("Not run.")
    else:
        lines += [
            "Each row disables one safeguard in-process and re-runs the case that guards it. "
            f"Detected: **{sens['detected']} of {sens['total']}**.",
            "",
            "| Injected defect | Case | Detected | Caught by |",
            "|---|---|---|---|",
        ]
        for m in sens["mutations"]:
            caught = ", ".join(f"`{c}`" for c in m["caught_by"])
            lines.append(
                f"| {m['mutation']}: {m['breaks']} | {m['case']} | "
                f"{'yes' if m['detected'] else '**no**'} | {caught} |"
            )
    lines += ["", "## Baseline comparison", ""]
    lines += _baseline_md(r["baseline"])
    lines += ["", "## LLM judge (qualitative only)", ""]
    j = r["llm_judge"]
    if j.get("status") != "ran":
        lines.append(f"Not run: {j.get('reason', j.get('status'))}. Safety verdicts never use it.")
    else:
        lines += ["| Item | Rubric | Score | Pass |", "|---|---|---|---|"]
        for it in j["items"]:
            lines.append(f"| {it['item']} | {it['rubric']} | {it['score']} | {it['pass']} |")
    lines += ["", "## Representative traces", ""]
    for t in r["representative_traces"]:
        lines += [f"### {t['case']}: {t['title']}", "", "Commands (role, command, HTTP, code):", ""]
        for e in t["commands"]:
            tag = " (probe: must be refused)" if e.get("probe") else ""
            code = f" `{e['code']}`" if e.get("code") else ""
            lines.append(f"1. {e['as']} · `{e['command']}` → {e['http']}{code}{tag}")
        lines += ["", "<details><summary>Audit trail</summary>", ""]
        lines += [f"1. {x}" for x in t["audit_events"]]
        lines += ["", "</details>", ""]
    lines += ["## Known limitations", ""]
    lines += [f"- {x}" for x in r["known_limitations"]]
    lines += ["", "## Reproduce", "", "```bash", *r["reproduce"], "```", ""]
    return "\n".join(lines)


def _baseline_md(b: dict[str, Any]) -> list[str]:
    if b.get("status") != "ran":
        return [f"Not run: {b.get('reason', b.get('status'))}."]
    out = [
        b["description"],
        "",
        "| Measure | Single-pass baseline | Vera | Basis |",
        "|---|---|---|---|",
    ]
    for row in b["rows"]:
        out.append(f"| {row['measure']} | {row['baseline']} | {row['vera']} | {row['basis']} |")
    if b.get("not_compared"):
        out += ["", "Not compared:", ""]
        out += [f"- {x}" for x in b["not_compared"]]
    return out
