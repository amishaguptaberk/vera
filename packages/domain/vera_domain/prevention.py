"""Prevention Planner specialist: recommends card controls from the catalog.

The prompt carries record ids, kinds and field NAMES only; every value is read with `read_field`
and every recommendation cites {record_id, version, field, value}. The code validates grounding
and the catalog; it never decides which controls to recommend. Humans decide (propose/skip).
"""

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from vera_domain.investigation import Citation, PermittedRecord
from vera_domain.specialists import Finding, SpecialistSpec

PLANNER = "prevention_planner"
PROMPT_VERSION = "v1"
PERMITTED_KINDS = frozenset({"charge", "related_charge", "cardholder_profile", "initial_report"})
CATALOG = ("lock", "replace", "virtual", "block", "monitor")


class PlannerInput(BaseModel):
    case_id: str
    permitted_records: list[PermittedRecord]
    catalog: list[str]


class RecommendedControl(BaseModel):
    control: Literal["lock", "replace", "virtual", "block", "monitor"]
    reason: str = Field(min_length=1, max_length=500)
    citations: list[Citation] = Field(min_length=1)
    scope: str = Field(min_length=1)
    effect: str = Field(min_length=1)
    reversible: bool
    required_permission: Literal["card_admin"]


class PlannerOutput(BaseModel):
    controls: list[RecommendedControl] = Field(min_length=1, max_length=5)


def findings_of(output: BaseModel) -> list[Finding]:
    return [
        Finding(
            record_id=c.record_id,
            version=c.version,
            field=c.field,
            value=c.value,
            statement=r.reason,
        )
        for r in getattr(output, "controls", [])
        for c in r.citations
    ]


_SYSTEM = (
    "Prevention Planner. Purpose: after a provisional credit or dispute decision on a card "
    "dispute, recommend card controls that prevent repeat loss, chosen only from the catalog "
    "(lock, replace, virtual, block, monitor). You decide nothing and change no card: a human "
    "proposes or skips your plan and the card admin approves and applies it. Read every value "
    "you use with the read_field tool, only from the permitted records. For each control give "
    "the reason, citations {record_id, version, field, value} exactly as read_field returned "
    "them, scope (what it affects), effect, whether it is reversible, and required_permission "
    "'card_admin'. Reply with one JSON object only."
)


def build_messages(inputs: PlannerInput) -> list[dict[str, Any]]:
    schema = PlannerOutput.model_json_schema()
    return [
        {"role": "system", "content": f"{_SYSTEM}\n\nOutput JSON schema: {json.dumps(schema)}"},
        {"role": "user", "content": json.dumps(inputs.model_dump(), sort_keys=True)},
    ]


def planner_input(case_id: str, records: Mapping[str, tuple[str, list[str]]]) -> PlannerInput:
    return PlannerInput(
        case_id=case_id,
        permitted_records=[
            PermittedRecord(record_id=rid, kind=kind, fields=sorted(fields))
            for rid, (kind, fields) in sorted(records.items())
            if kind in PERMITTED_KINDS
        ],
        catalog=list(CATALOG),
    )


def build_spec(record_kinds: Mapping[str, str]) -> SpecialistSpec:
    allowed = frozenset(r for r, k in record_kinds.items() if k in PERMITTED_KINDS)

    def messages(inputs: BaseModel) -> list[dict[str, Any]]:
        return build_messages(PlannerInput.model_validate(inputs.model_dump()))

    return SpecialistSpec(
        name=PLANNER,
        prompt_version=PROMPT_VERSION,
        input_schema=PlannerInput,
        output_schema=PlannerOutput,
        allowed_tools=frozenset({"read_field"}),
        allowed_record_ids=lambda _case_id: allowed,
        build_messages=messages,
        findings_of=findings_of,
    )
