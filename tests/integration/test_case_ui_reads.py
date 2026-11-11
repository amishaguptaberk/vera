"""Read APIs for the case UI: queue next action, activity, assignable users, steps (VER-016)."""

from typing import Any

from fastapi.testclient import TestClient

CASE = "CHG-1042"


def act(client: TestClient, command: str, payload: dict[str, Any] | None = None) -> None:
    view = client.get(f"/api/cases/{CASE}").json()
    action = next(a for a in view["available_actions"] if a["command"] == command)
    body = {**action["payload_defaults"], **(payload or {})}
    resp = client.post(
        f"/api/cases/{CASE}/commands/{command}",
        json={
            "idempotency_key": action["idempotency_key"],
            "expected_case_version": view["case_version"],
            "payload": body,
        },
    )
    assert resp.status_code == 200, resp.text


HOLD = {"reason": "Waiting for the bank", "next_owner": "usr-dana-okafor"}


def queue(client: TestClient) -> dict[str, dict[str, Any]]:
    resp = client.get("/api/cases")
    assert resp.status_code == 200
    return {r["case_id"]: r for r in resp.json()}


def test_live_queue_row_next_action_and_waiting_on_follow_state(client: TestClient) -> None:
    row = queue(client)[CASE]
    view = client.get(f"/api/cases/{CASE}").json()
    assert row["next_action"] == "Open the case and start the investigation"
    assert row["next_action"] == view["next_action"]
    assert row["waiting_on"] is None
    assert row["blocker"] == "Not investigated"
    assert row["due_today"] is True

    act(client, "open_case")
    row = queue(client)[CASE]
    assert row["next_action"] == "Start the investigation"
    assert row["waiting_on"] is None

    act(client, "hold_case", HOLD)
    row = queue(client)[CASE]
    view = client.get(f"/api/cases/{CASE}").json()
    assert row["next_action"] == "Resume when the next owner is ready"
    assert row["next_action"] == view["next_action"]
    assert row["waiting_on"] == "Dana Okafor"
    assert view["waiting_on"] == {"id": "usr-dana-okafor", "name": "Dana Okafor"}
    assert row["blocker"] == "On hold"


def test_display_rows_carry_the_seeded_spec_strings(client: TestClient) -> None:
    rows = queue(client)
    assert rows["CHG-1029"]["next_action"] == "Send reminder or reassign"
    assert rows["CHG-1029"]["waiting_on"] == "Marcus Chen"
    assert rows["CHG-1029"]["blocker"] == "Reply overdue"
    assert rows["CHG-1029"]["wait_kind"] == "cardholder"
    assert rows["CHG-1039"]["waiting_on"] == "Dana Okafor"
    assert rows["CHG-1039"]["wait_kind"] == "reviewer"
    assert rows["CHG-1051"]["waiting_on"] is None
    assert rows["CHG-1051"]["next_action"] == "Investigate related charge"
    assert rows["CHG-1036"]["blocker"] == "Merchant response"
    assert rows["CHG-1033"]["blocker"] == "Receipt missing"
    assert rows["CHG-1033"]["waiting_on"] == "Ana Ruiz"


def test_filter_counts_use_the_demo_clock(client: TestClient) -> None:
    resp = client.get("/api/cases/filter-counts")
    assert resp.status_code == 200
    # Demo clock 2026-11-10 ~09:00: 1029 overdue (7:00); 1039, 1051, 1042 due later today.
    # Waiting on me (Sam, nobody else waited on, open): 1042, 1051, 1036.
    assert resp.json() == {
        "all": 6,
        "due_today": 3,
        "overdue": 1,
        "mine": 3,
        "cardholder": 2,
        "reviewer": 1,
    }
    rows = queue(client)
    assert rows["CHG-1029"]["due_today"] is False
    assert rows["CHG-1033"]["due_today"] is False


def test_activity_in_order_with_after_and_access(client: TestClient) -> None:
    act(client, "open_case")
    act(client, "hold_case", HOLD)
    act(client, "resume_case")
    resp = client.get(f"/api/cases/{CASE}/activity")
    assert resp.status_code == 200
    events = resp.json()["events"]
    types = [e["type"] for e in events]
    assert types[-3:] == ["case.opened", "case.held", "case.resumed"]
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    held = events[-2]
    assert held["summary"] == "Case put on hold"
    assert held["actor_name"] == "Sam Rivera"
    assert held["actor_role"] == "analyst"
    assert CASE in held["record_ids"]

    newer = client.get(f"/api/cases/{CASE}/activity", params={"after": held["id"]}).json()
    assert [e["type"] for e in newer["events"]] == ["case.resumed"]

    assert client.get("/api/cases/CHG-9999/activity").status_code == 404
    assert client.get("/api/cases/CHG-9999/activity").json()["code"] == "case_not_found"

    client.post("/api/session/role", json={"role": "cardholder"})
    assert client.get(f"/api/cases/{CASE}/activity").status_code == 403


def test_assignable_users_are_staff_only(client: TestClient) -> None:
    resp = client.get("/api/users", params={"assignable": "true"})
    assert resp.status_code == 200
    users = {u["id"]: u for u in resp.json()["users"]}
    assert set(users) == {"usr-sam-rivera", "usr-dana-okafor"}
    assert users["usr-sam-rivera"]["name"] == "Sam Rivera"
    assert sorted(users["usr-sam-rivera"]["roles"]) == ["analyst", "ops_admin"]
    assert sorted(users["usr-dana-okafor"]["roles"]) == ["card_admin", "reviewer"]

    client.post("/api/session/role", json={"role": "cardholder"})
    assert client.get("/api/users", params={"assignable": "true"}).status_code == 403


def test_case_view_steps_at_intake_open_and_held(client: TestClient) -> None:
    def statuses() -> list[tuple[str, str]]:
        steps = client.get(f"/api/cases/{CASE}").json()["steps"]
        return [(s["key"], s["status"]) for s in steps[:3]]

    assert statuses() == [
        ("report_received", "done"),
        ("investigate", "current"),
        ("request_info", "upcoming"),
    ]
    act(client, "open_case")
    assert statuses()[1] == ("investigate", "current")
    act(client, "hold_case", HOLD)
    assert statuses() == [
        ("report_received", "done"),
        ("investigate", "blocked"),
        ("request_info", "upcoming"),
    ]


def test_openapi_describes_new_routes_and_fields(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    for field in ("next_action", "waiting_on", "blocker", "wait_kind", "due_today"):
        assert field in schemas["QueueRow"]["properties"]
    assert "steps" in schemas["CaseView"]["properties"]
    for name in ("ActivityFeed", "ActivityEvent", "AssignableUsers", "FilterCounts"):
        assert name in schemas, name
    assert "/api/cases/{case_id}/activity" in spec["paths"]
    assert "/api/users" in spec["paths"]
