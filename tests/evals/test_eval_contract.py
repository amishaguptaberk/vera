"""Static checks on the evaluation suite itself (no database): the case contract is complete,
every required behaviour is covered, the LLM judge cannot reach a safety verdict, and the
report counts failures instead of hiding them."""

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from evals import baseline, cases, judge, report

ROOT = Path(__file__).resolve().parents[2]
CASES = cases.load_cases()


def test_suite_size_is_within_the_agreed_range() -> None:
    assert 36 <= len(CASES) <= 50


@pytest.mark.parametrize(("path", "case"), CASES, ids=[c["id"] for _, c in CASES])
def test_case_defines_the_full_contract(path: Path, case: dict[str, Any]) -> None:
    assert cases.contract_problems(case) == []
    assert path.name.startswith(case["id"] + "_")
    unknown = set(case) - set(cases.REQUIRED) - set(cases.OPTIONAL)
    assert not unknown, f"unknown fields {unknown}"
    assert case["initial_facts"]["merchant"] == "Northstar Equipment"
    for probe in case["forbidden_commands"]:
        assert {"as", "command"} <= set(probe)


def test_case_ids_are_unique() -> None:
    ids = [c["id"] for _, c in CASES]
    assert len(ids) == len(set(ids))


def test_every_required_behaviour_is_covered_by_a_case() -> None:
    covered = {slug for _, c in CASES for slug in c["covers"]}
    assert set(report.REQUIRED_COVERAGE) - covered == set()
    assert covered - set(report.REQUIRED_COVERAGE) - {"golden_case"} == set()


def test_golden_case_is_chg_1042_northstar() -> None:
    golden = next(c for _, c in CASES if c["id"] == "EC-01")
    f = golden["initial_facts"]
    assert (f["case_id"], f["merchant"], f["amount_cents"], f["card_last4"], f["cardholder"]) == (
        "CHG-1042",
        "Northstar Equipment",
        284000,
        "4418",
        "Priya Shah",
    )
    po = golden["source_records"]["records"]["PO-219"]
    assert (po["approved_quantity"], po["approved_amount_cents"]) == (1, 240000)
    assert golden["source_records"]["records"]["DLV-882"]["received_quantity"] == 2
    assert golden["source_records"]["absent_kinds"] == ["receipt"]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod)
            names |= {f"{mod}.{a.name}" for a in node.names}
    return names


@pytest.mark.parametrize(
    "module",
    [
        "evals/cases.py",
        "evals/sensitivity.py",
        "evals/baseline.py",
        "evals/report.py",
        *map(
            str, sorted(p.relative_to(ROOT) for p in (ROOT / "services/api/vera_api").glob("*.py"))
        ),
    ],
)
def test_no_safety_path_imports_the_llm_judge(module: str) -> None:
    names = _imports(ROOT / module)
    assert "evals.judge" not in names and not any(n.endswith(".judge") for n in names)


def test_judge_scores_only_bounded_qualitative_rubrics() -> None:
    allowed = {"follow_up_minimal", "finding_clarity", "call_summary_faithful"}
    assert allowed == judge.MAY_SCORE
    text = json.dumps(judge.RUBRICS).lower()
    for word in ("credit", "permission", "approve", "dispute", "close"):
        assert word not in text


class _Client:
    def __init__(self, content: dict[str, Any]) -> None:
        self.content = content

    def complete(self, **_: Any) -> Any:
        return type("R", (), {"content": self.content})()


def test_judge_output_outside_the_schema_is_never_a_pass() -> None:
    out = judge.run(_Client({"verdict": "approve credit", "pass": True}))
    assert out["status"] == "ran"
    assert all(item["pass"] is False and item["score"] is None for item in out["items"])


def test_judge_records_a_valid_structured_score() -> None:
    class Echo:
        def complete(self, *, messages: list[dict[str, Any]], **_: Any) -> Any:
            rubric = json.loads(messages[-1]["content"])["rubric"]
            content = {"rubric": rubric, "score": 5, "pass": True, "reasons": ["ok"]}
            return type("R", (), {"content": content})()

    out = judge.run(Echo())
    assert [i["score"] for i in out["items"]] == [5, 5, 5]


def test_judge_does_not_run_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert judge.run()["status"] == "not run"


def test_baseline_is_measured_and_deterministic() -> None:
    a, b = baseline.run(), baseline.run()
    assert a == b
    rows = {r["measure"]: r for r in a["rows"]}
    unsupported = rows["Unsupported claims stored (perturbed citations)"]
    assert unsupported["vera"].startswith("0/")
    assert rows["Reference citations wrongly rejected"]["vera"] == "0"


def _result(status: str, checks: list[cases.Check], probes: list[dict[str, Any]]) -> Any:
    return cases.CaseResult(
        "EC-99",
        "t",
        ["financial_safety"],
        ["duplicate_command"],
        status,
        checks=checks,
        probes=probes,
    )


def test_report_counts_failed_probes_and_checks_instead_of_hiding_them() -> None:
    bad_probe = {"gate": "permission", "passed": False}
    stale_probe = {"gate": "stale_approval", "passed": False}
    failed = cases.Check(
        "reliability.exactly_once_effects",
        "reliability",
        False,
        "2 x",
        counter="idempotency_failures",
    )
    r = report.build([_result("FAIL", [failed], [bad_probe, stale_probe])], [], None, None)
    assert r["summary"]["failed_cases"] == 1
    assert r["counters"]["permission_failures"] == 1
    assert r["counters"]["stale_approval_failures"] == 1
    assert r["counters"]["idempotency_failures"] == 1
    assert r["failures_by_category"]["reliability"] == 1
    md = report.markdown(r)
    assert "**FAIL**" in md and "**1**" in md


def test_judge_scores_cannot_change_any_verdict_or_counter() -> None:
    ok = cases.Check("workflow.steps", "workflow", True)
    failing_judge = {
        "status": "ran",
        "items": [{"item": "x", "rubric": "finding_clarity", "score": 1, "pass": False}],
    }
    without = report.build([_result("PASS", [ok], [])], [], None, None)
    with_judge = report.build([_result("PASS", [ok], [])], [], None, failing_judge)
    for key in ("summary", "counters", "failures_by_category", "cases", "coverage"):
        assert without[key] == with_judge[key]


def test_report_has_no_run_specific_identifiers() -> None:
    ok = cases.Check("workflow.steps", "workflow", True)
    r = report.build([_result("PASS", [ok], [])], [], None, None)
    blob = json.dumps(r)
    assert "run_" not in blob and "IDV-" not in blob


def test_case_catalogue_lists_every_case() -> None:
    doc = (ROOT / "docs" / "evaluation-cases.md").read_text()
    missing = [c["id"] for _, c in CASES if f"[{c['id']}]" not in doc]
    assert not missing, f"regenerate docs/evaluation-cases.md: {missing}"
