"""Optional LLM judge for bounded qualitative text. Never part of a safety verdict.

It scores exactly three things, each against a fixed rubric, and must answer with one JSON
object that validates against JudgeScore; anything else is recorded as invalid output, never
as a pass:

* follow_up_minimal  - does the follow-up ask the smallest set of questions the open findings need?
* finding_clarity    - is each finding statement clear, specific and tied to its cited values?
* call_summary_faithful - does the call result say only what the transcript says?

What it may never decide (and no code path lets it): whether credit is allowed, whether a
dispute can be submitted, whether card controls can be applied, whether a case can close, or
whether a user has permission. Those are decided by the gateway, the Policy Controller and the
deterministic evaluators in evals/cases.py, which do not import this module (a test checks it).

Runs only with --judge and NVIDIA_API_KEY (the same provider settings as the specialists). The
inputs are the reference outputs for CHG-1042, so the judged text is fixed and synthetic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
RECORDINGS = ROOT / "recordings"

Rubric = Literal["follow_up_minimal", "finding_clarity", "call_summary_faithful"]
RUBRICS: dict[str, str] = {
    "follow_up_minimal": (
        "Score 1-5. 5: every question maps to one open finding and no question asks for "
        "something already supported by the evidence; 3: one unnecessary or vague question; "
        "1: questions unrelated to the open findings. pass = score >= 4."
    ),
    "finding_clarity": (
        "Score 1-5. 5: each statement names the records and the exact values it compares and "
        "states the discrepancy plainly; 3: understandable but missing a value or record; "
        "1: vague or misleading. pass = score >= 4."
    ),
    "call_summary_faithful": (
        "Score 1-5. 5: the structured result (outcome, authorization answer, answers) states "
        "only what the quoted transcript lines say; 3: a minor overstatement; 1: claims not in "
        "the transcript. pass = score >= 4."
    ),
}
# The only things this module may score. Anything financial or permission-related is absent
# by construction.
MAY_SCORE = frozenset(RUBRICS)


class JudgeScore(BaseModel):
    rubric: Rubric
    score: int = Field(ge=1, le=5)
    passed: bool = Field(alias="pass")
    reasons: list[str] = Field(min_length=1, max_length=3)


def _final(specialist: str) -> dict[str, Any]:
    doc = json.loads((RECORDINGS / specialist / "v1" / "CHG-1042.1.json").read_text())
    return dict(doc["content"])


def items() -> list[tuple[str, Rubric, dict[str, Any]]]:
    """The judged text: reference outputs for the golden case (fixed, synthetic)."""
    follow = _final("cardholder_follow_up")
    findings = [
        f.get("statement", "")
        for s in (
            "charge_investigator",
            "related_transaction_investigator",
            "receipt_document_reviewer",
        )
        for f in _final(s).get("findings", [])
    ]
    call = _final("live_verification_agent")
    from vera_api.callbacks import _SCRIPTS

    transcript = [t for _speaker, t in _SCRIPTS["confirmed"]]
    return [
        (
            "CHG-1042 follow-up",
            "follow_up_minimal",
            {
                "open_findings": [
                    "no receipt on file for a $2,840.00 charge",
                    "report says the cardholder does not recognize the charge",
                ],
                "supported": ["charge amount", "purchase order PO-219", "delivery DLV-882"],
                "questions": [q["text"] for q in follow["questions"]],
            },
        ),
        ("CHG-1042 findings", "finding_clarity", {"statements": findings}),
        (
            "CHG-1042 call result",
            "call_summary_faithful",
            {
                "transcript_contact_lines": transcript,
                "structured_result": call,
            },
        ),
    ]


def _messages(rubric: Rubric, payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": (
                "You grade one piece of text against a fixed rubric. You never decide money, "
                "permissions, closure or policy. Answer with one JSON object: "
                '{"rubric": <name>, "score": 1-5, "pass": true|false, "reasons": [1-3 strings]}.'
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {"rubric": rubric, "rubric_text": RUBRICS[rubric], "input": payload}
            ),
        },
    ]


def run(client: Any | None = None) -> dict[str, Any]:
    if client is None:
        if not os.environ.get("NVIDIA_API_KEY"):
            return {"status": "not run", "reason": "NVIDIA_API_KEY is not set"}
        from vera_api.model_client import LiveModelClient

        client = LiveModelClient()
    out = []
    for name, rubric, payload in items():
        try:
            res = client.complete(
                specialist="eval_judge",
                prompt_version="judge-v1",
                messages=_messages(rubric, payload),
                response_schema=JudgeScore.model_json_schema(by_alias=True),
                tools=[],
            )
            score = JudgeScore.model_validate(res.content)
            if score.rubric != rubric:
                raise ValueError(f"answered rubric {score.rubric}, asked {rubric}")
            out.append(
                {
                    "item": name,
                    "rubric": rubric,
                    "score": score.score,
                    "pass": score.passed,
                    "reasons": score.reasons,
                }
            )
        except Exception as exc:  # invalid or failed output is recorded, never a pass
            out.append(
                {
                    "item": name,
                    "rubric": rubric,
                    "score": None,
                    "pass": False,
                    "reasons": [f"invalid judge output: {type(exc).__name__}"],
                }
            )
    return {
        "status": "ran",
        "rubrics": RUBRICS,
        "items": out,
        "note": "Qualitative only; no safety, permission or money verdict uses this.",
    }
