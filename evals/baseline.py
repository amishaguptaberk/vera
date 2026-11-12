"""Baseline comparison: a single-pass, single-agent pipeline versus Vera's workflow.

Measured only where the repository supports a real measurement, from the reference recordings
and the synthetic seed (no model call, no database):

* Single-pass baseline: one agent (the Charge Investigator's reference output) reads the case
  once; its findings are accepted after schema validation only, with no grounding validator.
* Vera: three investigation specialists in the checkpointed graph, each finding accepted only
  if validate_grounding finds its cited value at the cited record version.

Unsupported claims are measured on deterministic perturbations of every reference citation
(wrong value, wrong version, unknown field, unknown record): the claims a schema-only pipeline
would store versus those Vera's validator lets through. Comparisons the code cannot support
without inventing the baseline's behaviour are listed under not_compared, with the reason.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RECORDINGS = ROOT / "recordings"
INVESTIGATORS = (
    "charge_investigator",
    "related_transaction_investigator",
    "receipt_document_reviewer",
)
# The golden case's expected facts, as the (record, field) citations that establish each.
GOLDEN_FACTS: dict[str, set[tuple[str, str]]] = {
    "amount mismatch ($2,840 charged vs $2,400 approved)": {
        ("CHG-1042", "amount_cents"),
        ("PO-219", "approved_amount_cents"),
    },
    "quantity mismatch (1 approved, 2 delivered)": {
        ("PO-219", "approved_quantity"),
        ("DLV-882", "received_quantity"),
    },
    "missing receipt above the $75 threshold": {("CHG-1042", "amount_cents")},
    "related charge CHG-1051 at the same merchant": {
        ("CHG-1051", "merchant"),
        ("CHG-1051", "amount_cents"),
    },
}
FACT_KIND = {
    "amount mismatch ($2,840 charged vs $2,400 approved)": "conflict",
    "quantity mismatch (1 approved, 2 delivered)": "conflict",
    "missing receipt above the $75 threshold": "discrepancy",
    "related charge CHG-1051 at the same merchant": "related_charge",
}


def _findings(specialist: str) -> list[dict[str, Any]]:
    doc = json.loads((RECORDINGS / specialist / "v1" / "CHG-1042.1.json").read_text())
    return list(doc["content"].get("findings", []))


def _covered(findings: list[dict[str, Any]]) -> list[str]:
    out = []
    for fact, cites in GOLDEN_FACTS.items():
        for f in findings:
            have = {(c["record_id"], c["field"]) for c in f.get("citations", [])}
            if f.get("kind") == FACT_KIND[fact] and cites <= have:
                out.append(fact)
                break
    return out


def _reader() -> Any:
    """read_field over the synthetic seed (every record at version 1)."""
    from vera_api.evidence import _SEED_RECORDS

    fields = {rid: dict(f) for rid, _kind, _status, f in _SEED_RECORDS}

    def read(record_id: str, field: str) -> tuple[Any, int]:
        if record_id not in fields or field not in fields[record_id]:
            raise LookupError(f"{record_id}.{field}")
        return fields[record_id][field], 1

    return read


def _perturb(c: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    value = c["value"]
    wrong = value + 100 if isinstance(value, int) else f"{value} (edited)"
    return [
        ("wrong value", {**c, "value": wrong}),
        ("wrong version", {**c, "version": c["version"] + 1}),
        ("unknown field", {**c, "field": c["field"] + "_total"}),
        ("unknown record", {**c, "record_id": "PO-999"}),
    ]


def run() -> dict[str, Any]:
    from vera_domain.specialists import Finding, validate_grounding

    single = _findings("charge_investigator")
    vera = [f for s in INVESTIGATORS for f in _findings(s)]
    cov_single, cov_vera = _covered(single), _covered(vera)

    read = _reader()
    total = 0
    accepted_vera = 0
    reference_rejected = 0
    by_kind: dict[str, int] = {}
    for f in vera:
        for c in f.get("citations", []):
            ref = Finding(**{k: c[k] for k in ("record_id", "version", "field", "value")})
            reference_rejected += len(validate_grounding([ref], read)) > 0
            for kind, bad in _perturb(c):
                total += 1
                claim = Finding(**{k: bad[k] for k in ("record_id", "version", "field", "value")})
                if not validate_grounding([claim], read):
                    accepted_vera += 1
                    by_kind[kind] = by_kind.get(kind, 0) + 1
    conflicts_single = sum(f.get("kind") == "conflict" for f in single)
    conflicts_vera = sum(f.get("kind") == "conflict" for f in vera)
    n = len(GOLDEN_FACTS)
    return {
        "status": "ran",
        "description": (
            "Single-pass baseline: one agent (the Charge Investigator's reference output) whose "
            "findings are stored after schema validation only. Vera: three investigation "
            "specialists whose findings must pass the grounding validator. Measured on the "
            "reference recordings and the synthetic seed; no model is called."
        ),
        "rows": [
            {
                "measure": "Evidence coverage (golden facts found)",
                "baseline": f"{len(cov_single)}/{n}",
                "vera": f"{len(cov_vera)}/{n}",
                "basis": "reference recordings vs the 4 CHG-1042 facts",
            },
            {
                "measure": "Contradictions detected at investigation",
                "baseline": str(conflicts_single),
                "vera": str(conflicts_vera),
                "basis": "conflict findings in the investigation output",
            },
            {
                "measure": "Unsupported claims stored (perturbed citations)",
                "baseline": f"{total}/{total}",
                "vera": f"{accepted_vera}/{total}",
                "basis": "4 perturbations of each reference citation; schema-only vs "
                "validate_grounding",
            },
            {
                "measure": "Reference citations wrongly rejected",
                "baseline": "0",
                "vera": str(reference_rejected),
                "basis": "false positives of the validator on the reference output",
            },
        ],
        "missed_by_baseline": sorted(set(cov_vera) - set(cov_single)),
        "unsupported_accepted_by_vera": by_kind,
        "not_compared": [
            "Next-question quality: no single-pass follow-up exists in the code to compare; "
            "Vera's follow-up is checked deterministically (EC-03: at most 2 questions, asks for "
            "the receipt, never re-asks supported items).",
            "Safe routing: a single-pass agent with direct adapter access has no gate to measure; "
            "Vera's gates are measured instead by the forbidden-command probes in this report.",
            "Recovery: the code has no non-checkpointed mode to run; Vera's resume is measured in "
            "EC-21 and EC-22 (no specialist step repeated after a timeout or crash).",
        ],
    }
