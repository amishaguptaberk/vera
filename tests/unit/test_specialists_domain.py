import pytest
from vera_domain.specialists import (
    ExecutionMode,
    FailureReason,
    Finding,
    StepStatus,
    _same,
    validate_grounding,
)

SOURCE = {("CHG-1042", "amount"): ("2,480.00", 3), ("CHG-1042", "quantity"): (10, 3)}


def read_field(record_id: str, field: str) -> tuple[object, int]:
    return SOURCE[(record_id, field)]


def test_enums_have_contract_values() -> None:
    assert {m.value for m in ExecutionMode} == {"live", "replay"}
    assert {s.value for s in StepStatus} == {"queued", "running", "succeeded", "failed"}
    assert {r.value for r in FailureReason} == {
        "schema_invalid",
        "ungrounded",
        "apply_failed",
        "timeout",
        "provider_error",
        "scope_violation",
        "missing_recording",
    }


def test_matching_finding_has_no_violation() -> None:
    f = Finding(record_id="CHG-1042", version=3, field="amount", value="2,480.00")
    assert validate_grounding([f], read_field) == []


def test_mismatched_value_is_a_violation() -> None:
    f = Finding(record_id="CHG-1042", version=3, field="amount", value="2,840.00")
    [v] = validate_grounding([f], read_field)
    assert v.index == 0 and v.code == "value_mismatch"
    assert "2,840.00" in v.message and "2,480.00" in v.message


def test_wrong_version_and_missing_field_are_violations() -> None:
    wrong_version = Finding(record_id="CHG-1042", version=2, field="quantity", value=10)
    missing = Finding(record_id="CHG-1042", version=3, field="nope", value=1)
    vs = validate_grounding([wrong_version, missing], read_field_lenient)
    assert [(v.index, v.code) for v in vs] == [(0, "version_mismatch"), (1, "not_found")]


def read_field_lenient(record_id: str, field: str) -> tuple[object, int]:
    if (record_id, field) not in SOURCE:
        raise LookupError(field)
    return SOURCE[(record_id, field)]


def test_numeric_equivalence_is_not_string_sensitive() -> None:
    f = Finding(record_id="CHG-1042", version=3, field="amount", value="2480.00")
    assert validate_grounding([f], read_field) == []


@pytest.mark.parametrize(
    ("source", "cited"),
    [
        ("28,40", 2840),
        ("1,2", "12"),
        ("0042", "42"),
        (True, 1),
        ("1e3", "1000"),
        ("2840", "28.40"),
        (284000, "2840.00"),
        ("USD 2840", "EUR 2840"),
    ],
)
def test_wrong_values_are_not_grounded(source: object, cited: object) -> None:
    assert not _same(source, cited)
    assert not _same(cited, source)


@pytest.mark.parametrize(
    ("source", "cited"),
    [("2,840.00", "2840.00"), (2840, "2840.00"), (2840.0, 2840)],
)
def test_equal_numbers_in_different_notation_are_grounded(source: object, cited: object) -> None:
    assert _same(source, cited)
    assert _same(cited, source)
