"""Snapshot hash and material-field rules (pure)."""

from vera_domain.commands import REGISTRY
from vera_domain.evidence import (
    SERVICE_REGISTRY,
    EvidenceStatus,
    compute_snapshot_hash,
    content_hash,
)

POLICY = {"policy_version": 1, "receipt_threshold_cents": 7500}
VERSIONS = [("PO-219", 1, "aa"), ("DLV-882", 1, "bb"), ("CHG-1042", 1, "cc")]


def test_hash_is_sha256_hex_and_order_independent() -> None:
    h = compute_snapshot_hash(VERSIONS, POLICY)
    assert len(h) == 64 and int(h, 16) >= 0
    assert compute_snapshot_hash(list(reversed(VERSIONS)), POLICY) == h


def test_hash_changes_with_a_version_or_policy_field() -> None:
    base = compute_snapshot_hash(VERSIONS, POLICY)
    bumped = [("DLV-882", 2, "bb") if r == "DLV-882" else (r, v, c) for r, v, c in VERSIONS]
    assert compute_snapshot_hash(bumped, POLICY) != base
    assert compute_snapshot_hash(VERSIONS, {**POLICY, "receipt_threshold_cents": 10000}) != base


def test_content_hash_ignores_non_material_fields_only() -> None:
    a = {"received_quantity": 2, "note": "dock"}
    assert content_hash("delivery_record", {**a, "note": "other"}) == content_hash(
        "delivery_record", a
    )
    assert content_hash("delivery_record", {**a, "received_quantity": 1}) != content_hash(
        "delivery_record", a
    )


def test_statuses_and_service_commands_are_kept_out_of_human_registry() -> None:
    assert {s.value for s in EvidenceStatus} == {
        "supporting", "missing", "conflicting", "superseded", "pending_review", "not_relevant",
    }  # fmt: skip
    assert {"link_evidence", "record_claim", "record_finding"} <= set(SERVICE_REGISTRY)
    assert not set(SERVICE_REGISTRY) & set(REGISTRY)
