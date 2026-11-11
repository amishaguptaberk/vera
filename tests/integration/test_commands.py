"""Command gateway: role gate, version gate, replay, hold/resume, actions, session (VER-002)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from vera_domain.commands import RECOVERY_ONLY, REGISTRY
from vera_domain.enums import Role

HUMAN_ROLES = [Role.ANALYST, Role.OPS_ADMIN, Role.REVIEWER, Role.CARD_ADMIN, Role.CARDHOLDER]
CASE = "CHG-1042"

PAYLOADS: dict[str, dict[str, Any]] = {
    "open_case": {},
    "hold_case": {"reason": "Waiting for the bank", "next_owner": "usr-dana-okafor"},
    "resume_case": {},
    "reassign_case": {"to": "usr-dana-okafor", "reason": "Card program owns this"},
    "link_report": {"report_id": "REP-1047", "statement": "Second call about the same charge."},
    "evaluate_policy": {},
    "start_investigation": {},
    "retry_specialist_step": {"step_key": "charge_investigator", "mode": "replay"},
}


USER_INPUTS: dict[str, dict[str, Any]] = {
    "open_case": {},
    "hold_case": {"reason": "Waiting for the bank", "next_owner": "usr-dana-okafor"},
    "resume_case": {},
    "reassign_case": {"to": "usr-dana-okafor", "reason": "Card program owns this"},
    "link_report": {"statement": "Second call about the same charge."},
    "evaluate_policy": {},
    "start_investigation": {},
    "retry_specialist_step": {"step_key": "charge_investigator", "mode": "replay"},
}


def switch(client: TestClient, role: Role) -> None:
    resp = client.post("/api/session/role", json={"role": role.value})
    assert resp.status_code == 200, resp.text


def set_session(client: TestClient, value: str) -> None:
    """Make `value` the only session cookie sent. httpx2's jar keeps a server-set cookie
    (domain testserver.local) beside a manually set one (no domain) and sends both."""
    client.cookies.clear()
    client.cookies.set("vera_session", value)


def version(client: TestClient, case_id: str = CASE) -> int:
    return client.get(f"/api/cases/{case_id}").json()["case_version"]  # type: ignore[no-any-return]


def key_for(client: TestClient, command: str, payload: dict[str, Any], case_id: str = CASE) -> str:
    """The key the server resolves: template filled from case, actor and payload."""
    uid = client.get("/api/session").json()["user"]["id"]
    return REGISTRY[command].key_template.format(
        case_id=case_id, case_version=version(client, case_id), user_id=uid, **payload
    )


def send(
    client: TestClient,
    command: str,
    *,
    key: str | None = None,
    payload: dict[str, Any] | None = None,
    expected: int | None = None,
    case_id: str = CASE,
) -> Any:
    body = PAYLOADS[command] if payload is None else payload
    return client.post(
        f"/api/cases/{case_id}/commands/{command}",
        json={
            "idempotency_key": key or key_for(client, command, body, case_id),
            "expected_case_version": version(client, case_id) if expected is None else expected,
            "payload": body,
        },
    )


@pytest.fixture
def snap(db_url: str) -> Iterator[Any]:
    engine = create_engine(db_url)

    def take() -> dict[str, Any]:
        with engine.connect() as conn:
            out: dict[str, Any] = {
                t: conn.execute(text(f"select count(*) from {t}")).scalar_one()
                for t in ("audit_events", "state_transitions", "idempotency_keys")
            }
            out["case"] = tuple(
                conn.execute(
                    text("select case_version, state, step, owner_id from cases where id=:i"),
                    {"i": CASE},
                ).one()
            )
        return out

    yield take
    engine.dispose()


def forbidden_pairs() -> list[tuple[str, Role]]:
    return [(n, r) for n, s in REGISTRY.items() for r in Role if r not in s.roles]


@pytest.mark.parametrize(("command", "role"), forbidden_pairs())
def test_role_that_does_not_hold_command_gets_403_and_nothing_is_written(
    client: TestClient, db_url: str, snap: Any, command: str, role: Role
) -> None:
    before = snap()
    if role in HUMAN_ROLES:
        switch(client, role)
        resp = send(client, command, key=f"k-{command}-{role}")
        assert resp.status_code == 403
        assert resp.json()["code"] == "role_forbidden"
    else:
        from sqlalchemy.orm import sessionmaker
        from vera_api.auth import Actor
        from vera_api.gateway import execute_command
        from vera_domain.clock import default_demo_clock
        from vera_domain.errors import CommandError

        engine = create_engine(db_url)
        actor = Actor(
            user_id=f"{role.value}:x", name="svc", active_role=role, roles=frozenset({role})
        )
        with sessionmaker(engine)() as session, pytest.raises(CommandError) as err:
            execute_command(
                session,
                now=default_demo_clock().now(),
                case_id=CASE,
                command=command,
                key=f"k-{command}-{role}",
                expected_version=before["case"][0],
                payload=PAYLOADS[command],
                actor=actor,
                request_id="t",
            )
        engine.dispose()
        assert err.value.code == "role_forbidden"
        assert err.value.http_status == 403
    assert snap() == before


def test_wrong_expected_case_version_is_409_and_changes_nothing(
    client: TestClient, snap: Any
) -> None:
    before = snap()
    resp = send(client, "open_case", key="open:CHG-1042:x", expected=before["case"][0] + 5)
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "stale_case_version"
    assert body["case_version"] == before["case"][0]
    assert snap() == before


def test_same_key_replays_original_result_and_only_attempts_change(
    client: TestClient, db_url: str, snap: Any
) -> None:
    first = send(client, "hold_case", key="hold:CHG-1042:1")
    assert first.status_code == 200 and first.json()["status"] == "recorded"
    after_first = snap()
    again = send(client, "hold_case", key="hold:CHG-1042:1", expected=1)  # stale version is fine
    assert again.status_code == 200
    assert again.json()["status"] == "replayed"
    assert again.json()["result"] == first.json()["result"]
    assert again.json()["event_ids"] == first.json()["event_ids"]
    assert snap() == after_first
    engine = create_engine(db_url)
    with engine.connect() as conn:
        attempts = conn.execute(
            text("select attempts from idempotency_keys where key='hold:CHG-1042:1'")
        ).scalar_one()
    engine.dispose()
    assert attempts == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"next_owner": "usr-dana-okafor"},
        {"reason": "Waiting for the bank"},
        {"reason": "abcd", "next_owner": "usr-dana-okafor"},
        {"reason": "     ", "next_owner": "usr-dana-okafor"},
        {"reason": "Waiting for the bank", "next_owner": "   "},
        {"reason": "Waiting for the bank", "next_owner": "usr-nobody"},
    ],
)
def test_hold_needs_reason_and_next_owner(
    client: TestClient, snap: Any, payload: dict[str, Any]
) -> None:
    before = snap()
    resp = send(client, "hold_case", payload=payload)
    assert resp.status_code == 422
    assert resp.json()["code"] == "schema_invalid"
    assert snap() == before


def test_resume_rederives_step_from_case_facts(client: TestClient, db_url: str) -> None:
    assert send(client, "open_case", key="open:CHG-1042:usr-sam-rivera").status_code == 200
    held = send(client, "hold_case").json()["case"]
    assert (held["state"], held["step"], held["state_label"]) == ("held", "onhold", "On hold")
    assert held["owner"]["id"] == "usr-dana-okafor"
    resumed = send(client, "resume_case").json()["case"]
    assert (resumed["state"], resumed["step"]) == ("investigating", "intake")
    assert resumed["state_label"] == "Needs investigation"
    assert resumed["hold"] is None
    # History before the hold is still there: open, hold, resume rows plus creation.
    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "select next_state from state_transitions where case_id='CHG-1042' order by id"
                )
            )
            .scalars()
            .all()
        )
    engine.dispose()
    assert rows == ["reported", "investigating", "held", "investigating"]
    # A case held before it was opened returns to where it would have been: new report.
    client.post("/api/demo/reset")
    send(client, "hold_case")
    back = send(client, "resume_case").json()["case"]
    assert (back["state"], back["step"]) == ("reported", "intake")


def test_invalid_step_closed_and_non_openable(client: TestClient, db_url: str) -> None:
    resp = send(client, "resume_case", key="resume:x")
    assert resp.status_code == 409 and resp.json()["code"] == "invalid_step"
    assert resp.json()["blocked_reason"]
    assert send(client, "open_case").status_code == 200
    assert send(client, "open_case", key="o2").json()["code"] == "invalid_step"

    r = send(client, "open_case", key="o3", case_id="CHG-1029", expected=1)
    assert r.status_code == 404 and r.json()["code"] == "case_not_openable"
    r = send(client, "open_case", key="o3", case_id="CHG-9999", expected=1)
    assert r.status_code == 404 and r.json()["code"] == "case_not_found"

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("update cases set state='closed' where id='CHG-1042'"))
    engine.dispose()
    r = send(client, "hold_case", key="h-closed")
    assert r.status_code == 409 and r.json()["code"] == "case_closed"


def _scenario_setups() -> dict[str, list[str]]:
    return {"new": [], "opened": ["open_case"], "held": ["hold_case"]}


@pytest.mark.parametrize("role", HUMAN_ROLES)
@pytest.mark.parametrize("scenario", ["new", "opened", "held"])
def test_enabled_actions_are_accepted_and_blocked_ones_rejected_with_same_reason(
    client: TestClient, role: Role, scenario: str
) -> None:
    def setup() -> None:
        client.post("/api/demo/reset")
        switch(client, Role.ANALYST)
        for cmd in _scenario_setups()[scenario]:
            assert send(client, cmd).status_code == 200
        switch(client, role)

    setup()
    view = client.get(f"/api/cases/{CASE}").json()
    listed = client.get(f"/api/cases/{CASE}/available-actions").json()
    assert listed == view["available_actions"]
    held_by_role = {
        n for n, s in REGISTRY.items() if role in s.roles and n not in RECOVERY_ONLY
    }  # recovery-only commands are listed in recovery_actions, never here
    assert {a["command"] for a in listed} | {
        b["command"] for b in view["blocked_actions"]
    } == held_by_role
    assert all(a["enabled"] and a["role"] == role.value for a in listed)

    for action in listed:
        setup()
        assert "{" not in action["idempotency_key"] and "}" not in action["idempotency_key"]
        assert "key_fields" not in action
        body = {**action["payload_defaults"], **USER_INPUTS[action["command"]]}
        resp = client.post(
            f"/api/cases/{CASE}/commands/{action['command']}",
            json={
                "expected_case_version": view["case_version"],
                "idempotency_key": action["idempotency_key"],
                "payload": body,
            },
        )
        assert resp.status_code == 200, (action["command"], resp.text)
    for blocked in view["blocked_actions"]:
        setup()
        resp = send(client, blocked["command"], key="blocked-probe")
        assert resp.status_code == 409
        assert resp.json()["blocked_reason"] == blocked["reason"] == blocked["blocked_reason"]


def test_primary_action_and_resolved_keys(client: TestClient) -> None:
    actions = client.get(f"/api/cases/{CASE}/available-actions").json()
    assert actions[0]["command"] == "open_case"
    assert actions[0]["idempotency_key"] == "open:CHG-1042:usr-sam-rivera"
    assert actions[0]["expected_state"] == "reported"
    hold = next(a for a in actions if a["command"] == "hold_case")
    assert hold["idempotency_key"] == "hold:CHG-1042:1"


def counts(db_url: str) -> dict[str, Any]:
    engine = create_engine(db_url)
    tables = [
        "users", "user_roles", "cases", "reports", "audit_events", "state_transitions",
        "idempotency_keys", "case_assignments",
    ]  # fmt: skip
    with engine.connect() as conn:
        out: dict[str, Any] = {
            t: conn.execute(text(f"select count(*) from {t}")).scalar_one() for t in tables
        }
        out["versions"] = conn.execute(
            text("select id, case_version, state, step, owner_id from cases order by id")
        ).all()
    engine.dispose()
    return out


def test_switching_role_writes_no_command_event_or_version(client: TestClient, db_url: str) -> None:
    before = counts(db_url)
    for role in HUMAN_ROLES:
        resp = client.post("/api/session/role", json={"role": role.value})
        assert resp.status_code == 200
        body = client.get("/api/session").json()
        assert body["active_role"] == role.value
        assert role.value in body["roles"]
        assert body["environment"] == "synthetic"
    assert client.get("/api/session").json()["user"]["name"] == "Priya Shah"
    assert counts(db_url) == before


@pytest.mark.parametrize(
    ("command", "role", "actor_id"),
    [
        ("open_case", Role.ANALYST, "usr-sam-rivera"),
        ("hold_case", Role.ANALYST, "usr-sam-rivera"),
        ("reassign_case", Role.ANALYST, "usr-sam-rivera"),
        ("link_report", Role.ANALYST, "usr-sam-rivera"),
        ("link_report", Role.CARDHOLDER, "usr-priya-shah"),
    ],
)
def test_accepted_command_appends_one_transition_and_declared_events(
    client: TestClient, db_url: str, command: str, role: Role, actor_id: str
) -> None:
    switch(client, role)
    before = counts(db_url)
    resp = send(client, command, key=None)
    assert resp.status_code == 200, resp.text
    after = counts(db_url)
    spec = REGISTRY[command]
    assert after["state_transitions"] == before["state_transitions"] + 1
    assert after["audit_events"] == before["audit_events"] + len(spec.events)
    assert resp.json()["case"]["case_version"] == 2
    engine = create_engine(db_url)
    with engine.connect() as conn:
        t = conn.execute(
            text(
                "select * from state_transitions where case_id='CHG-1042' order by id desc limit 1"
            )
        ).one()
        ev = conn.execute(
            text("select * from audit_events where case_id='CHG-1042' order by id desc")
        ).all()
    engine.dispose()
    assert t.actor_role == role.value and t.actor_id == actor_id
    assert t.case_version == 2 and t.event_id is not None
    assert [e.type for e in reversed(ev[: len(spec.events)])] == [e.value for e in spec.events]
    assert all(
        e.actor_role == role.value and e.actor_id == actor_id for e in ev[: len(spec.events)]
    )
    if command == "link_report":
        assert (t.prior_state, t.prior_step) == (t.next_state, t.next_step)
        assert ev[0].type == "report.linked"


def test_duplicate_report_retry_adds_no_second_event(client: TestClient, db_url: str) -> None:
    dup = {"report_id": "REP-1043", "transaction_id": "TXN-1042", "statement": "again"}
    switch(client, Role.CARDHOLDER)
    assert client.post("/api/reports", json=dup).status_code == 200
    mid = counts(db_url)
    assert client.post("/api/reports", json=dup).status_code == 200
    assert counts(db_url) == mid
    # The command and the intake path share the key report:{report_id}.
    r = send(
        client,
        "link_report",
        key="report:REP-1043",
        payload={"report_id": "REP-1043", "statement": "again"},
    )
    assert r.json()["status"] == "replayed"
    assert counts(db_url) == mid


# --- session RBAC -------------------------------------------------------------------------


def test_role_endpoint_rejects_service_and_unknown_roles_without_cookie_change(
    client: TestClient,
) -> None:
    switch(client, Role.REVIEWER)
    cookie = client.cookies.get("vera_session")
    for bad in ("system", "specialist", "policy_controller", "adapter", "root"):
        resp = client.post("/api/session/role", json={"role": bad})
        assert resp.status_code in (403, 422)
        assert "set-cookie" not in resp.headers
        assert client.cookies.get("vera_session") == cookie
    assert client.get("/api/session").json()["active_role"] == "reviewer"


def test_role_endpoint_is_absent_outside_synthetic(db_url: str) -> None:
    from vera_api.app import create_app
    from vera_api.config import Settings

    app = create_app(Settings(database_url=db_url, env="staging", session_secret="s3cret"))
    with TestClient(app) as c:
        assert c.post("/api/session/role", json={"role": "analyst"}).status_code == 404
        r = c.post(
            f"/api/cases/{CASE}/commands/open_case",
            json={"idempotency_key": "k", "expected_case_version": 1, "payload": {}},
        )
        assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url=db_url, env="staging", session_secret=""))


def test_server_chooses_user_from_user_roles(client: TestClient) -> None:
    resp = client.post(
        "/api/session/role",
        json={"role": "card_admin", "user_id": "usr-sam-rivera"},
    )
    assert resp.status_code == 200
    assert client.get("/api/session").json()["user"]["id"] == "usr-dana-okafor"
    switch(client, Role.CARDHOLDER)
    assert client.get("/api/session").json()["user"]["id"] == "usr-priya-shah"


def test_tampered_or_unsigned_cookie_is_no_session(client: TestClient) -> None:
    switch(client, Role.REVIEWER)
    good = client.cookies.get("vera_session")
    assert good is not None
    body, _, mac = good.rpartition(".")
    set_session(client, f"{body}.{'0' * len(mac)}")
    assert client.get("/api/session").json()["user"]["id"] == "usr-sam-rivera"
    assert client.get("/api/session").json()["active_role"] == "analyst"
    set_session(client, "garbage")
    assert client.get("/api/session").json()["active_role"] == "analyst"


@pytest.mark.parametrize("tampered_first", [True, False])
def test_valid_plus_tampered_session_cookie_is_no_session(
    client: TestClient, tampered_first: bool
) -> None:
    switch(client, Role.REVIEWER)
    good = client.cookies.get("vera_session")
    assert good is not None
    body, _, mac = good.rpartition(".")
    tampered = f"{body}.{'0' * len(mac)}"
    pair = [f"vera_session={tampered}", f"vera_session={good}"]
    header = "; ".join(pair if tampered_first else pair[::-1])
    client.cookies.clear()
    session = client.get("/api/session", headers={"Cookie": header}).json()
    assert session["user"]["id"] == "usr-sam-rivera"
    assert session["active_role"] == "analyst"


def test_two_session_cookies_are_401_outside_synthetic(client: TestClient, db_url: str) -> None:
    from vera_api.app import create_app
    from vera_api.auth import sign
    from vera_api.config import Settings

    good = sign("s3cret", "usr-dana-okafor", "reviewer")
    body, _, mac = good.rpartition(".")
    tampered = f"{body}.{'0' * len(mac)}"
    app = create_app(Settings(database_url=db_url, env="staging", session_secret="s3cret"))
    with TestClient(app) as c:
        ok = c.get("/api/session", headers={"Cookie": f"vera_session={good}"})
        assert ok.status_code == 200 and ok.json()["user"]["id"] == "usr-dana-okafor"
        for header in (
            f"vera_session={tampered}; vera_session={good}",
            f"vera_session={good}; vera_session={tampered}",
            f"vera_session={good}; vera_session={good}",
        ):
            resp = c.get("/api/session", headers={"Cookie": header})
            assert resp.status_code == 401 and resp.json()["code"] == "unauthenticated"


def test_validly_signed_cookie_for_role_not_in_user_roles_is_403(
    client: TestClient, db_url: str, snap: Any
) -> None:
    from vera_api.auth import sign
    from vera_api.config import DEV_SESSION_SECRET

    before = snap()
    for user, role in (("usr-sam-rivera", "card_admin"), ("usr-sam-rivera", "reviewer")):
        set_session(client, sign(DEV_SESSION_SECRET, user, role))
        resp = send(client, "open_case", key=f"forged-{role}")
        assert resp.status_code == 403 and resp.json()["code"] == "role_forbidden"
    # Even a held, signed role that lacks the command is refused (ops_admin holds no command).
    set_session(client, sign(DEV_SESSION_SECRET, "usr-sam-rivera", "ops_admin"))
    assert send(client, "open_case", key="ops").status_code == 403
    assert snap() == before
    # A role removed from user_roles after the cookie was issued stops working at once.
    switch(client, Role.ANALYST)
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("delete from user_roles where user_id='usr-sam-rivera' and role='analyst'")
        )
    engine.dispose()
    resp = send(client, "open_case", key="revoked")
    assert resp.status_code == 403 and resp.json()["code"] == "role_forbidden"


# --- repair round 1 -----------------------------------------------------------------------


def close_case(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("update cases set state='closed', step='closed' where id='CHG-1042'"))
    engine.dispose()


def test_duplicate_report_on_closed_case_is_409_and_writes_nothing(
    client: TestClient, db_url: str
) -> None:
    close_case(db_url)
    before = counts(db_url)
    dup = {"report_id": "REP-1050", "transaction_id": "TXN-1042", "statement": "again"}
    resp = client.post("/api/reports", json=dup)
    assert resp.status_code == 409 and resp.json()["code"] == "case_closed"
    assert counts(db_url) == before


def test_link_report_key_is_enforced_and_repeat_replays(client: TestClient, db_url: str) -> None:
    before = counts(db_url)
    bad = send(client, "link_report", key="x1")
    assert bad.status_code == 422 and bad.json()["code"] == "idempotency_key_mismatch"
    assert counts(db_url) == before
    assert send(client, "link_report").json()["status"] == "recorded"
    mid = counts(db_url)
    again = send(client, "link_report", key="report:REP-1047", expected=1)
    assert again.status_code == 200 and again.json()["status"] == "replayed"
    assert counts(db_url) == mid


def test_link_report_rejects_the_cases_own_original_report(client: TestClient, db_url: str) -> None:
    before = counts(db_url)
    p = {"report_id": "REP-1042", "statement": "x"}
    resp = send(client, "link_report", payload=p)
    assert resp.status_code == 422
    assert counts(db_url) == before


def test_link_report_creates_the_linked_report_record(client: TestClient, db_url: str) -> None:
    assert send(client, "link_report").status_code == 200
    engine = create_engine(db_url)
    with engine.connect() as conn:
        row = conn.execute(text("select case_id, statement from reports where id='REP-1047'")).one()
    engine.dispose()
    assert tuple(row) == (CASE, "Second call about the same charge.")


def test_replay_with_other_payload_or_role_is_a_conflict(client: TestClient, db_url: str) -> None:
    assert send(client, "link_report").status_code == 200
    mid = counts(db_url)
    other = {"report_id": "REP-1048", "statement": "x"}
    r = send(client, "link_report", key="report:REP-1047", payload=other)
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_conflict"
    switch(client, Role.CARDHOLDER)
    r = send(client, "link_report", key="report:REP-1047")
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_conflict"
    assert counts(db_url) == mid


def test_intake_derives_state_and_uses_user_id_as_actor(client: TestClient, db_url: str) -> None:
    from vera_domain.enums import CaseState, CaseStep
    from vera_domain.facts import CaseFacts, derive_step

    state, step = derive_step(
        CaseFacts(opened_at=None, closed=False, hold=None, owner_id="usr-sam-rivera", due_at=None)
    )
    engine = create_engine(db_url)
    with engine.connect() as conn:
        c = conn.execute(text("select state, step from cases where id='CHG-1042'")).one()
        actors = conn.execute(
            text("select actor_id from audit_events where case_id='CHG-1042'")
        ).all()
        t_actor = conn.execute(
            text("select actor_id from state_transitions where case_id='CHG-1042'")
        ).all()
    engine.dispose()
    assert tuple(c) == (state.value, step.value)
    assert (state, step) == (CaseState.REPORTED, CaseStep.INTAKE)
    assert {a[0] for a in actors} == {"usr-priya-shah"} == {a[0] for a in t_actor}


@pytest.mark.parametrize("owner", ["Priya Shah", "usr-priya-shah"])
def test_cardholder_cannot_become_case_owner(client: TestClient, snap: Any, owner: str) -> None:
    before = snap()
    p = {"reason": "Waiting for the bank", "next_owner": owner}
    resp = send(client, "hold_case", payload=p)
    assert resp.status_code == 422 and resp.json()["code"] == "schema_invalid"
    assert snap() == before


# --- repair round 2 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"to": "usr-dana-okafor", "reason": " "},
        {"to": "usr-dana-okafor", "reason": ""},
        {"to": "   ", "reason": "Card program owns this"},
    ],
)
def test_reassign_needs_non_blank_reason_and_target(
    client: TestClient, snap: Any, payload: dict[str, Any]
) -> None:
    before = snap()
    resp = send(client, "reassign_case", payload=payload)
    assert resp.status_code == 422 and resp.json()["code"] == "schema_invalid"
    assert snap() == before


@pytest.mark.parametrize(
    "payload", [{"report_id": "  ", "statement": "x"}, {"report_id": "REP-1047", "statement": " "}]
)
def test_link_report_needs_non_blank_fields(
    client: TestClient, snap: Any, payload: dict[str, Any]
) -> None:
    before = snap()
    resp = send(client, "link_report", key="report:x", payload=payload)
    assert resp.status_code == 422 and resp.json()["code"] == "schema_invalid"
    assert snap() == before


def test_another_user_reusing_a_key_is_a_conflict_and_writes_nothing(
    client: TestClient, db_url: str
) -> None:
    assert send(client, "open_case", key="open:CHG-1042:usr-sam-rivera").status_code == 200
    assert send(client, "hold_case", key="hold:CHG-1042:2").status_code == 200
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("insert into users (id, name) values ('usr-alex-kim', 'Alex Kim')"))
        conn.execute(
            text("insert into user_roles (user_id, role) values ('usr-alex-kim', 'analyst')")
        )
    from vera_api.auth import sign
    from vera_api.config import DEV_SESSION_SECRET

    def attempts() -> list[Any]:
        with engine.connect() as conn:
            return conn.execute(
                text("select key, attempts from idempotency_keys order by key")
            ).all()

    before, rows = counts(db_url), attempts()
    set_session(client, sign(DEV_SESSION_SECRET, "usr-alex-kim", "analyst"))
    for cmd, key in (
        ("open_case", "open:CHG-1042:usr-sam-rivera"),
        ("hold_case", "hold:CHG-1042:2"),
    ):
        resp = send(client, cmd, key=key, expected=3)
        assert resp.status_code == 409 and resp.json()["code"] == "idempotency_key_conflict"
    assert counts(db_url) == before
    assert attempts() == rows
    engine.dispose()


def test_literal_key_template_is_rejected(client: TestClient, snap: Any) -> None:
    before = snap()
    resp = send(client, "link_report", key="report:{report_id}")
    assert resp.status_code == 422 and resp.json()["code"] == "idempotency_key_mismatch"
    assert snap() == before


def test_link_report_action_view_allocates_the_next_report_id(client: TestClient) -> None:
    actions = client.get(f"/api/cases/{CASE}/available-actions").json()
    link = next(a for a in actions if a["command"] == "link_report")
    assert link["payload_defaults"] == {"report_id": "REP-1043"}
    assert link["idempotency_key"] == "report:REP-1043"
    assert all(a["payload_defaults"] == {} for a in actions if a["command"] != "link_report")


def test_two_viewers_handed_the_same_report_id_first_link_wins(
    client: TestClient, snap: Any
) -> None:
    link = next(
        a
        for a in client.get(f"/api/cases/{CASE}/available-actions").json()
        if a["command"] == "link_report"
    )

    def post(statement: str, expected: int) -> Any:
        return client.post(
            f"/api/cases/{CASE}/commands/link_report",
            json={
                "expected_case_version": expected,
                "idempotency_key": link["idempotency_key"],
                "payload": {**link["payload_defaults"], "statement": statement},
            },
        )

    assert post("first", 1).status_code == 200
    after = snap()
    same = post("first", 1)
    assert same.status_code == 200 and same.json()["status"] == "replayed"
    other = post("second", 2)
    assert other.status_code == 409 and other.json()["code"] == "idempotency_key_conflict"
    assert snap() == after


def test_session_view_falls_back_when_cookie_role_is_not_held(client: TestClient) -> None:
    from vera_api.auth import sign
    from vera_api.config import DEV_SESSION_SECRET

    set_session(client, sign(DEV_SESSION_SECRET, "usr-sam-rivera", "card_admin"))
    body = client.get("/api/session").json()
    assert body["user"]["id"] == "usr-sam-rivera"
    assert body["active_role"] == "analyst"
    assert "card_admin" not in body["roles"]


def insert_reports(db_url: str, ids: list[str]) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        card = conn.execute(text("select cardholder_id from reports limit 1")).scalar_one()
        for rid in ids:
            conn.execute(
                text(
                    "insert into reports (id, case_id, cardholder_id, statement, received_at)"
                    " values (:i, :c, :h, 'bad data', now())"
                ),
                {"i": rid, "c": CASE, "h": card},
            )
    engine.dispose()


def test_bad_stored_report_ids_never_break_reads_or_commands(
    client: TestClient, db_url: str
) -> None:
    insert_reports(db_url, ["REP-²", "REP-abc", "REP-99999999999999999999"])
    assert client.get(f"/api/cases/{CASE}").status_code == 200
    actions = client.get(f"/api/cases/{CASE}/available-actions")
    assert actions.status_code == 200
    link = next(a for a in actions.json() if a["command"] == "link_report")
    assert link["payload_defaults"] == {"report_id": "REP-1043"}
    assert send(client, "hold_case").status_code == 200


def test_huge_stored_numeric_id_does_not_move_the_sequence(client: TestClient, db_url: str) -> None:
    insert_reports(db_url, ["REP-1234567890123"])
    actions = client.get(f"/api/cases/{CASE}/available-actions").json()
    link = next(a for a in actions if a["command"] == "link_report")
    assert link["payload_defaults"] == {"report_id": "REP-1043"}


@pytest.mark.parametrize("bad", ["REP-²", "REP-1\x00", "REP-" + "9" * 5000, "", "  ", "REP 1"])
def test_intake_rejects_invalid_report_ids(client: TestClient, db_url: str, bad: str) -> None:
    before = counts(db_url)
    body = {"report_id": bad, "transaction_id": "TXN-1042", "statement": "dup"}
    resp = client.post("/api/reports", json=body)
    assert resp.status_code == 422 and resp.json()["code"] == "schema_invalid"
    assert counts(db_url) == before


@pytest.mark.parametrize("bad", ["REP-²", "REP-1\x00", "REP-" + "9" * 5000])
def test_link_report_command_rejects_invalid_report_ids(
    client: TestClient, db_url: str, bad: str
) -> None:
    before = counts(db_url)
    resp = send(client, "link_report", payload={"report_id": bad, "statement": "x"})
    assert resp.status_code == 422 and resp.json()["code"] == "schema_invalid"
    assert counts(db_url) == before


@pytest.mark.parametrize("statement", ["   ", ""])
@pytest.mark.parametrize("txn", ["TXN-1042", "TXN-1051"])
def test_intake_rejects_blank_statements(
    client: TestClient, db_url: str, statement: str, txn: str
) -> None:
    before = counts(db_url)
    body = {"report_id": "REP-7777", "transaction_id": txn, "statement": statement}
    resp = client.post("/api/reports", json=body)
    assert resp.status_code == 422 and resp.json()["code"] == "schema_invalid"
    assert counts(db_url) == before


def test_intake_trailing_whitespace_stores_stripped_and_replays(
    client: TestClient, db_url: str
) -> None:
    switch(client, Role.CARDHOLDER)
    spaced = {"report_id": "REP-1043", "transaction_id": "TXN-1042", "statement": "again  "}
    assert client.post("/api/reports", json=spaced).status_code == 200
    mid = counts(db_url)
    engine = create_engine(db_url)
    with engine.connect() as conn:
        stored = conn.execute(
            text("select statement from reports where id='REP-1043'")
        ).scalar_one()
    engine.dispose()
    assert stored == "again"
    assert client.post("/api/reports", json={**spaced, "statement": "again"}).status_code == 200
    r = send(
        client,
        "link_report",
        key="report:REP-1043",
        payload={"report_id": "REP-1043", "statement": "again  "},
    )
    assert r.json()["status"] == "replayed"
    assert counts(db_url) == mid
