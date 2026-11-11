"""Specialist contracts (plan §18): pure types and the grounding validator. No I/O."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class ExecutionMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"


class StepStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FailureReason(StrEnum):
    SCHEMA_INVALID = "schema_invalid"
    UNGROUNDED = "ungrounded"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    SCOPE_VIOLATION = "scope_violation"
    MISSING_RECORDING = "missing_recording"


class Finding(BaseModel):
    """A draft finding: one cited fact. It is only a claim until grounding accepts it."""

    record_id: str
    version: int
    field: str
    value: Any
    statement: str = ""


def _findings_attr(output: BaseModel) -> list[Finding]:
    found = getattr(output, "findings", [])
    return list(found)


def _no_records(case_id: str) -> frozenset[str]:
    return frozenset()


def _default_messages(inputs: BaseModel) -> list[dict[str, Any]]:
    return [{"role": "user", "content": inputs.model_dump_json()}]


@dataclass(frozen=True)
class SpecialistSpec:
    name: str
    prompt_version: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    allowed_tools: frozenset[str] = frozenset({"read_field"})
    # Scope rule: the record ids this specialist may read for a case.
    allowed_record_ids: Callable[[str], frozenset[str]] = _no_records
    build_messages: Callable[[BaseModel], list[dict[str, Any]]] = _default_messages
    findings_of: Callable[[BaseModel], list[Finding]] = field(default=_findings_attr)


@dataclass(frozen=True)
class Violation:
    index: int
    code: str  # not_found | version_mismatch | value_mismatch
    message: str


ReadField = Callable[[str, str], tuple[Any, int]]


_GROUPED = re.compile(r"-?\d{1,3}(,\d{3})+(\.\d+)?")
_PLAIN = re.compile(r"-?(0|[1-9]\d*)(\.\d+)?")


def _number(v: Any) -> Decimal | None:
    """A strictly numeric value as Decimal: numbers (never bool) or well-formed numeric strings
    (thousands separators only in groups of three, no leading zeros, no exponent)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int | Decimal):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, str):
        t = v.strip()
        if _GROUPED.fullmatch(t) or _PLAIN.fullmatch(t):
            return Decimal(t.replace(",", ""))
    return None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    na, nb = _number(a), _number(b)
    if na is not None and nb is not None:
        return na == nb
    return str(a).strip() == str(b).strip()


def validate_grounding(findings: list[Finding], read_field: ReadField) -> list[Violation]:
    """A finding is grounded only if its cited value equals the source field at that version."""
    out: list[Violation] = []
    for i, f in enumerate(findings):
        cite = f"{f.record_id}.{f.field}"
        try:
            value, version = read_field(f.record_id, f.field)
        except LookupError:
            out.append(Violation(i, "not_found", f"{cite} does not exist"))
            continue
        if version != f.version:
            out.append(
                Violation(i, "version_mismatch", f"{cite} is at version {version}, not {f.version}")
            )
        elif not _same(value, f.value):
            out.append(
                Violation(
                    i,
                    "value_mismatch",
                    f"{cite} cites {f.value!r} but the source value is {value!r}",
                )
            )
    return out
