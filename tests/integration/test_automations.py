from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from vera_domain.enums import Role

WF = "card-dispute"


def switch(client: TestClient, role: Role) -> None:
    assert client.post("/api/session/role", json={"role": role.value}).status_code == 200


def cmd(client: TestClient, name: str, key: str, version: int, /, **payload: Any) -> Any:
    return client.post(
        f"/api/automations/commands/{name}",
        json={"idempotency_key": key, "expected_version": version, "payload": payload},
    )


def new_draft(client: TestClient) -> None:
    switch(client, Role.OPS_ADMIN)
    r = cmd(client, "create_workflow_draft", f"wfdraft:{WF}:3", 3, from_version=3)
    assert r.status_code == 200, r.json()
    assert r.json()["result"] == {"draft_version": 4}


def test_removing_policy_controller_is_rejected_naming_node_and_rule(client: TestClient) -> None:
    new_draft(client)
    r = cmd(
        client,
        "update_workflow_draft",
        f"wfpatch:{WF}:4:0",
        0,
        draft_version=4,
        ops=[{"op": "remove_node", "key": "pc2"}],
    )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "required_control_removed"
    assert "Rule 9" in body["message"] and "pc2" in body["message"]
    assert "Policy Controller" in body["message"]
    # the draft is unchanged
    assert client.get(f"/api/automations/workflows/{WF}").json()["draft"]["revision"] == 0


@pytest.mark.parametrize(
    "op",
    [
        {"op": "remove_node", "key": "analyst_decision"},  # human checkpoint + decision record
        {"op": "remove_node", "key": "reviewer_approval"},
        {"op": "remove_node", "key": "decision_packet_preparer"},  # evidence recheck
        {"op": "update_node", "key": "credit_executor", "changes": {"provides": []}},  # idem gate
    ],
)
def test_removing_required_controls_is_rejected(client: TestClient, op: dict[str, Any]) -> None:
    new_draft(client)
    r = cmd(client, "update_workflow_draft", f"wfpatch:{WF}:4:0", 0, draft_version=4, ops=[op])
    assert r.status_code == 422 and "Rule 9" in r.json()["message"]


def test_publish_blocked_until_checks_ran_on_exact_graph(client: TestClient) -> None:
    new_draft(client)
    r = cmd(
        client,
        "publish_workflow_version",
        f"wfpub:{WF}:4",
        0,
        draft_version=4,
        reason="Tighten callbacks",
    )
    assert r.status_code == 422 and r.json()["code"] == "checks_required"
    wf = client.get(f"/api/automations/workflows/{WF}").json()
    gh = wf["draft"]["graph_hash"]
    r = cmd(client, "run_workflow_checks", f"wfcheck:{WF}:4:{gh}", 0, draft_version=4)
    assert r.status_code == 200 and r.json()["result"]["passed"] is True
    assert len(r.json()["result"]["results"]) == 6
    # an edit after the check run invalidates it
    r = cmd(
        client,
        "update_workflow_draft",
        f"wfpatch:{WF}:4:0",
        0,
        draft_version=4,
        ops=[{"op": "update_node", "key": "pc1", "changes": {"label": "Evidence check"}}],
    )
    assert r.status_code == 200, r.json()
    r = cmd(
        client,
        "publish_workflow_version",
        f"wfpub:{WF}:4",
        1,
        draft_version=4,
        reason="Tighten callbacks",
    )
    assert r.status_code == 422 and r.json()["code"] == "checks_required"


def test_publish_with_unlimited_loop_is_blocked_by_validation(client: TestClient) -> None:
    new_draft(client)
    r = cmd(
        client,
        "update_workflow_draft",
        f"wfpatch:{WF}:4:0",
        0,
        draft_version=4,
        ops=[
            {
                "op": "remove_edge",
                "edge": {
                    "source": "retry_within_limits",
                    "target": "cardholder_follow_up",
                    "outcome": "retry",
                },
            },
            {
                "op": "add_edge",
                "edge": {
                    "source": "retry_within_limits",
                    "target": "cardholder_follow_up",
                    "outcome": "retry",
                },
            },
        ],
    )
    assert r.status_code == 200
    assert any(v["rule"] == 8 for v in r.json()["result"]["validation"])
    r = cmd(client, "publish_workflow_version", f"wfpub:{WF}:4", 1, draft_version=4, reason="x y z")
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert "Rule 8" in r.json()["message"]


def publish_v4(client: TestClient) -> Any:
    new_draft(client)
    gh = client.get(f"/api/automations/workflows/{WF}").json()["draft"]["graph_hash"]
    assert (
        cmd(client, "run_workflow_checks", f"wfcheck:{WF}:4:{gh}", 0, draft_version=4).status_code
        == 200
    )
    return cmd(
        client,
        "publish_workflow_version",
        f"wfpub:{WF}:4",
        0,
        draft_version=4,
        reason="Adds callback retry",
    )


def test_publish_v4_keeps_chg1042_pinned(client: TestClient, db_url: str) -> None:
    switch(client, Role.OPS_ADMIN)
    used = client.get(f"/api/automations/workflows/{WF}").json()["used_by"]
    before = {c["case_id"]: c for c in used}["CHG-1042"]
    r = publish_v4(client)
    assert r.status_code == 200, r.json()
    assert r.json()["result"] == {"active_version": 4}
    wf = client.get(f"/api/automations/workflows/{WF}").json()
    assert wf["active_version"] == 4 and wf["draft"] is None
    assert [v["version"] for v in wf["versions"]] == [3, 4]
    pinned = {c["case_id"]: c for c in wf["used_by"]}["CHG-1042"]
    assert pinned["workflow_version"] == before["workflow_version"] == 3
    # replay with the same key returns the stored result, no second version
    again = cmd(
        client,
        "publish_workflow_version",
        f"wfpub:{WF}:4",
        0,
        draft_version=4,
        reason="Adds callback retry",
    )
    assert again.json()["status"] == "replayed"
    events = client.get("/api/automations/events").json()
    assert [e["type"] for e in events][-1] == "workflow.published"
    assert events[-1]["actor_role"] == "ops_admin"


def test_published_version_is_immutable_at_the_database(client: TestClient, db_url: str) -> None:
    client.get(f"/api/automations/workflows/{WF}")
    engine = create_engine(db_url)
    for sql in (
        "update workflow_versions set reason='x' where version=3",
        "delete from workflow_versions where version=3",
        "update policy_versions set rules='[]' where version=1",
    ):
        with engine.begin() as conn, pytest.raises(Exception, match="append-only|forbid|immutable"):
            conn.execute(text(sql))
    engine.dispose()


def test_roles(client: TestClient) -> None:
    switch(client, Role.ANALYST)
    r = cmd(client, "create_workflow_draft", f"wfdraft:{WF}:3", 3, from_version=3)
    assert r.status_code == 403
    assert client.get(f"/api/automations/workflows/{WF}").status_code == 200
    switch(client, Role.REVIEWER)
    assert client.get("/api/automations/specialists").status_code == 200
    switch(client, Role.CARDHOLDER)
    assert client.get(f"/api/automations/workflows/{WF}").status_code == 403
    assert (
        cmd(client, "create_workflow_draft", f"wfdraft:{WF}:3", 3, from_version=3).status_code
        == 403
    )


def test_key_conflict_and_stale_version(client: TestClient) -> None:
    new_draft(client)
    r = cmd(
        client, "create_workflow_draft", f"wfdraft:{WF}:3", 3, from_version=3, workflow_id="other"
    )
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_conflict"
    r = cmd(
        client,
        "update_workflow_draft",
        f"wfpatch:{WF}:4:5",
        5,
        draft_version=4,
        ops=[{"op": "update_node", "key": "pc1", "changes": {"label": "x"}}],
    )
    assert r.status_code == 409 and r.json()["code"] == "stale_version"


SPEC = {
    "specialist_id": "chargeback_reason_coder",
    "name": "Reason coder",
    "purpose": "Suggest a network reason code from the evidence.",
    "records": ["CHG-1042"],
    "tools": ["read_evidence_field"],
    "output_type": "reason_code",
    "handoff": "pc2",
}


def test_specialist_prohibited_tool_and_add_to_workflow(client: TestClient) -> None:
    switch(client, Role.OPS_ADMIN)
    bad = {**SPEC, "tools": ["move_money"]}
    r = cmd(client, "create_specialist_draft", "spec:chargeback_reason_coder:new", 0, **bad)
    assert r.status_code == 422 and r.json()["code"] == "prohibited_tool"
    r = cmd(client, "create_specialist_draft", "spec:chargeback_reason_coder:new", 0, **SPEC)
    assert r.status_code == 200 and r.json()["result"]["status"] == "draft"
    r = cmd(
        client,
        "update_specialist_draft",
        "spec:chargeback_reason_coder:0",
        0,
        **{**SPEC, "purpose": "Suggest a reason code for the packet."},
    )
    assert r.status_code == 200 and r.json()["result"]["revision"] == 1
    r = cmd(
        client,
        "add_specialist_to_workflow",
        f"spec-wf:chargeback_reason_coder:{WF}:3",
        3,
        specialist_id="chargeback_reason_coder",
        from_version=3,
    )
    assert r.status_code == 200, r.json()
    assert r.json()["result"] == {"draft_version": 4, "node_id": "chargeback_reason_coder_1"}
    wf = client.get(f"/api/automations/workflows/{WF}").json()
    assert wf["active_version"] == 3
    assert all(n["key"] != "chargeback_reason_coder_1" for n in wf["graph"]["nodes"])
    assert any(n["key"] == "chargeback_reason_coder_1" for n in wf["draft"]["graph"]["nodes"])
    assert wf["draft"]["validation"] == []


def test_policy_draft_threshold_range_and_pinning(client: TestClient) -> None:
    switch(client, Role.OPS_ADMIN)
    r = cmd(
        client,
        "create_policy_draft",
        "poldraft:card-charge-investigation:1",
        1,
        policy_id="card-charge-investigation",
        from_version=1,
    )
    assert r.status_code == 200, r.json()
    assert r.json()["result"] == {"draft_version": 2}
    r = cmd(
        client,
        "publish_policy_version",
        "polpub:card-charge-investigation:2",
        1,
        policy_id="card-charge-investigation",
        draft_version=2,
        receipt_threshold=501,
        reason="Raise threshold",
    )
    assert r.status_code == 422 and r.json()["code"] == "schema_invalid"
    r = cmd(
        client,
        "publish_policy_version",
        "polpub:card-charge-investigation:2",
        1,
        policy_id="card-charge-investigation",
        draft_version=2,
        receipt_threshold=100,
        reason="Raise threshold",
    )
    assert r.status_code == 200 and r.json()["result"] == {"active_version": 2}
    pol = client.get("/api/policies/card-charge-investigation").json()
    assert pol["version"] == 2
    assert any(rule.get("params", {}).get("threshold_cents") == 10000 for rule in pol["rules"])
    used = client.get(f"/api/automations/workflows/{WF}").json()["used_by"]
    assert {c["case_id"]: c for c in used}["CHG-1042"]["policy_version"] == 1
