"""VER-006 identity verification through the HTTP seam and the command gateway."""

import logging
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from command_payloads import register_reducer_extras, register_test_payloads
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import adapters, gateway
from vera_api import identity as identity_mod
from vera_api.auth import Actor
from vera_api.identity import ADAPTER, identity_verified
from vera_api.models import Case
from vera_api.worker import run_once
from vera_domain.clock import default_demo_clock
from vera_domain.enums import Role
from vera_domain.errors import CommandError

CASE = "CHG-1042"

register_test_payloads(
    {
        "send_verification_request": {"channel": "otp"},
        "resend_verification_request": {"verification_id": "IDV-NONE"},
        "cancel_verification_request": {"verification_id": "IDV-NONE"},
        "submit_otp": {"verification_id": "IDV-NONE", "code": "000000"},
        "answer_verification_push": {"verification_id": "IDV-NONE", "approve": True},
        "expire_verification_request": {"verification_id": "IDV-NONE"},
    }
)
# What each identity effect puts in ctx.extra (reducer/declared-events test).
_IDV_EXTRA = {"verification_id": "IDV-1", "status": "requested", "channel": "otp"}
register_reducer_extras(
    {
        "send_verification_request": _IDV_EXTRA,
        "resend_verification_request": _IDV_EXTRA,
        "cancel_verification_request": {**_IDV_EXTRA, "status": "cancelled"},
        "expire_verification_request": {**_IDV_EXTRA, "status": "expired"},
        "submit_otp": {**_IDV_EXTRA, "status": "verified", "outcome": "accepted"},
        "answer_verification_push": {**_IDV_EXTRA, "status": "verified", "outcome": "approved"},
    }
)


def _upstream(session: Session, case: Case) -> dict[str, Any]:
    """Test-only provider standing in for VER-005: the reply was reviewed as incomplete."""
    return {"followup_status": "responded", "response_review": "incomplete"}


@pytest.fixture(autouse=True)
def _seams(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [*gateway.FACT_PROVIDERS, _upstream])
    yield
    adapters.ADAPTERS.pop(ADAPTER, None)


@pytest.fixture
def factory(client: TestClient, db_url: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(db_url)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def switch(client: TestClient, role: Role) -> None:
    assert client.post("/api/session/role", json={"role": role.value}).status_code == 200


def view(client: TestClient) -> dict[str, Any]:
    return client.get(f"/api/cases/{CASE}").json()  # type: ignore[no-any-return]


def command(client: TestClient, name: str, key: str, payload: dict[str, Any]) -> httpx.Response:
    return client.post(
        f"/api/cases/{CASE}/commands/{name}",
        json={
            "idempotency_key": key,
            "expected_case_version": view(client)["case_version"],
            "payload": payload,
        },
    )


def to_idv(client: TestClient) -> None:
    switch(client, Role.ANALYST)
    uid = client.get("/api/session").json()["user"]["id"]
    assert command(client, "open_case", f"open:{CASE}:{uid}", {}).status_code == 200
    v = view(client)
    assert (v["state"], v["step"]) == ("callback_pending", "idv")


def send(client: TestClient, channel: str = "otp") -> str:
    switch(client, Role.ANALYST)
    ver = view(client)["case_version"]
    r = command(client, "send_verification_request", f"idv:{CASE}:{ver}", {"channel": channel})
    assert r.status_code == 200, r.text
    return str(r.json()["result"]["verification_id"])


def outbox(client: TestClient, vid: str) -> dict[str, Any]:
    switch(client, Role.CARDHOLDER)
    r = client.get(f"/api/verifications/{vid}/outbox")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def submit(client: TestClient, vid: str, code: str, attempt: int) -> httpx.Response:
    switch(client, Role.CARDHOLDER)
    ver = client.get(f"/api/cases/{CASE}").json()
    version = ver.get("case_version")
    if version is None:  # cardholder cannot read the case view: use the db through staff
        switch(client, Role.ANALYST)
        version = view(client)["case_version"]
        switch(client, Role.CARDHOLDER)
    return client.post(
        f"/api/verifications/{vid}/submit_otp",
        json={
            "idempotency_key": f"otp:{vid}:{attempt}",
            "expected_case_version": version,
            "code": code,
        },
    )


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


def q(factory: sessionmaker[Session], sql: str) -> list[Any]:
    with factory() as s:
        return list(s.execute(text(sql)))


def test_three_wrong_codes_lock_the_request_as_the_cardholder(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client)
    code = outbox(client, vid)["code"]
    for n in (1, 2, 3):
        r = submit(client, vid, wrong(code), n)
        assert r.status_code == 200, r.text
        assert r.json()["result"]["outcome"] == "rejected"
    switch(client, Role.ANALYST)
    v = view(client)
    assert (v["state"], v["step"]) == ("callback_pending", "idv")
    rows = client.get(f"/api/cases/{CASE}/verifications").json()
    assert rows[0]["status"] == "failed" and rows[0]["attempts"] == 3
    rejected = q(
        factory, "select actor_role from audit_events where type='verification.code_rejected'"
    )
    assert [r[0] for r in rejected] == ["cardholder"] * 3
    locked = q(factory, "select actor_role from audit_events where type='verification.locked'")
    assert [r[0] for r in locked] == ["cardholder"]
    actions = {a["command"] for a in v["available_actions"]}
    assert {"send_verification_request", "hold_case", "reassign_case"} <= actions
    assert v["state"] != "closed"
    # The outbox is gone once the request is locked.
    switch(client, Role.CARDHOLDER)
    assert client.get(f"/api/verifications/{vid}/outbox").status_code == 404


def test_correct_code_verifies_and_replay_does_not_count_another_attempt(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    switch(client, Role.ANALYST)
    policy_before = view(client).get("policy")
    vid = send(client)
    code = outbox(client, vid)["code"]
    first = submit(client, vid, code, 1)
    assert first.status_code == 200 and first.json()["result"]["outcome"] == "accepted"
    again = client.post(
        f"/api/verifications/{vid}/submit_otp",
        json={"idempotency_key": f"otp:{vid}:1", "expected_case_version": 1, "code": code},
    )
    assert again.status_code == 200 and again.json()["status"] == "replayed"
    assert again.json()["result"] == first.json()["result"]
    switch(client, Role.ANALYST)
    v = view(client)
    assert (v["state"], v["step"]) == ("callback_pending", "verify")
    assert v.get("policy") == policy_before
    assert q(factory, "select count(*) from verification_attempts")[0][0] == 1
    with factory() as s:
        assert identity_verified(s, CASE)


def test_code_is_never_stored_logged_or_shown_to_staff(
    client: TestClient, factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    to_idv(client)
    vid = send(client)
    code = outbox(client, vid)["code"]
    assert len(code) == 6
    switch(client, Role.ANALYST)
    staff = [
        client.get(f"/api/cases/{CASE}/verifications").text,
        client.get(f"/api/cases/{CASE}").text,
        client.get(f"/api/cases/{CASE}/activity").text,
    ]
    assert client.get(f"/api/verifications/{vid}/outbox").status_code == 403
    # Analyst cannot submit the code.
    r = client.post(
        f"/api/verifications/{vid}/submit_otp",
        json={"idempotency_key": f"otp:{vid}:1", "expected_case_version": 1, "code": code},
    )
    assert r.status_code == 403
    assert (
        command(
            client, "submit_otp", f"otp:{vid}:1", {"verification_id": vid, "code": code}
        ).status_code
        == 403
    )
    assert submit(client, vid, wrong(code), 1).status_code == 200
    assert submit(client, vid, code, 2).status_code == 200
    dumps = [
        q(factory, f"select t::text from {t} t")
        for t in (
            "audit_events",
            "adapter_executions",
            "idempotency_keys",
            "identity_verifications",
            "verification_attempts",
        )
    ]
    blob = "\n".join(str(x) for x in dumps) + "\n".join(staff) + caplog.text
    assert code not in blob
    stored = q(factory, "select code_hash, code_salt from identity_verifications")[0]
    assert stored[0] and stored[1] and code not in stored[0]
    assert q(factory, "select count(*) from verification_outbox")[0][0] == 0


def test_expiry_is_recorded_once_resend_cooldown_429_and_new_send_new_key(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client)
    ver = view(client)["case_version"]
    r = command(
        client, "resend_verification_request", f"idv-resend:{vid}:2", {"verification_id": vid}
    )
    assert r.status_code == 429 and r.json()["code"] == "resend_cooldown", r.text
    assert view(client)["case_version"] == ver
    one = client.post(f"/api/demo/verifications/{vid}/expire")
    two = client.post(f"/api/demo/verifications/{vid}/expire")
    assert one.status_code == 200 and one.json()["status"] == "recorded", one.text
    assert two.status_code == 200 and two.json()["status"] == "replayed"
    expired = q(factory, "select count(*) from audit_events where type='verification.expired'")
    assert expired[0][0] == 1
    switch(client, Role.ANALYST)
    assert view(client)["step"] == "idv"
    vid2 = send(client)
    assert vid2 != vid
    keys = q(factory, "select key from idempotency_keys where key like 'idv:%' order by key")
    assert len(keys) == 2


def test_denied_push_is_declined_not_fraud_and_approved_push_verifies(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client, "push")
    assert outbox(client, vid)["code"] is None
    ver = view_version(client)
    switch(client, Role.CARDHOLDER)
    r = client.post(
        f"/api/verifications/{vid}/answer",
        json={"idempotency_key": f"push:{vid}", "expected_case_version": ver, "approve": False},
    )
    assert r.status_code == 200, r.text
    switch(client, Role.ANALYST)
    v = view(client)
    assert v["step"] == "idv" and v["state"] == "callback_pending"
    assert client.get(f"/api/cases/{CASE}/verifications").json()[0]["status"] == "declined"
    assert "send_verification_request" in {a["command"] for a in v["available_actions"]}
    declined = q(factory, "select actor_role from audit_events where type='verification.declined'")
    assert [r[0] for r in declined] == ["cardholder"]
    vid2 = send(client, "push")
    ver = view_version(client)
    switch(client, Role.CARDHOLDER)
    r = client.post(
        f"/api/verifications/{vid2}/answer",
        json={"idempotency_key": f"push:{vid2}", "expected_case_version": ver, "approve": True},
    )
    assert r.status_code == 200, r.text
    switch(client, Role.ANALYST)
    assert view(client)["step"] == "verify"


def test_cancel_returns_to_identity_check_and_other_cardholder_paths_are_closed(
    client: TestClient,
) -> None:
    to_idv(client)
    vid = send(client)
    r = command(
        client, "cancel_verification_request", f"idv-cancel:{vid}", {"verification_id": vid}
    )
    assert r.status_code == 200, r.text
    rows = client.get(f"/api/cases/{CASE}/verifications").json()
    assert rows[0]["status"] == "cancelled"
    switch(client, Role.CARDHOLDER)
    assert client.get(f"/api/verifications/{vid}/outbox").status_code == 404
    assert client.get(f"/api/cases/{CASE}/verifications").status_code == 403


def view_version(client: TestClient) -> int:
    switch(client, Role.ANALYST)
    return int(view(client)["case_version"])


# --- repair: D8 outside synthetic, outbox expiry, demo route auth, limits, races ---

ANALYST_ACTOR = Actor("usr-sam-rivera", "Sam Rivera", Role.ANALYST, frozenset({Role.ANALYST}))


def gw(s: Session, command_: str, key: str, payload: dict[str, Any]) -> gateway.Outcome:
    case = s.get(Case, CASE)
    assert case is not None
    s.refresh(case)
    version = case.case_version
    s.rollback()
    return gateway.execute_command(
        s,
        now=default_demo_clock().now(),
        case_id=CASE,
        command=command_,
        key=key,
        expected_version=version,
        payload=payload,
        actor=ANALYST_ACTOR,
        request_id="t",
    )


def test_outside_synthetic_the_code_is_not_stored_anywhere(
    client: TestClient, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    to_idv(client)
    monkeypatch.setenv("VERA_ENV", "production")
    monkeypatch.setenv("VERA_SESSION_SECRET", "s" * 40)
    seen: list[str] = []
    real = identity_mod.SIMULATED.take_code

    def spy(ref: str) -> str | None:
        code = real(ref)
        seen.append(code or "")
        return code

    monkeypatch.setattr(identity_mod.SIMULATED, "take_code", spy)
    with factory() as s:
        out = gw(s, "send_verification_request", f"idv:{CASE}:2", {"channel": "otp"})
    assert out.status == "recorded" and len(seen) == 1 and len(seen[0]) == 6
    assert q(factory, "select count(*) from verification_outbox")[0][0] == 0
    blob = "\n".join(
        str(q(factory, f"select t::text from {t} t"))
        for t in (
            "audit_events",
            "adapter_executions",
            "idempotency_keys",
            "identity_verifications",
            "verification_attempts",
            "verification_outbox",
        )
    )
    assert seen[0] not in blob


def test_outside_synthetic_without_a_secret_send_is_a_typed_503(
    client: TestClient, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    to_idv(client)
    monkeypatch.setenv("VERA_ENV", "production")
    monkeypatch.delenv("VERA_SESSION_SECRET", raising=False)
    with factory() as s, pytest.raises(CommandError) as err:
        gw(s, "send_verification_request", f"idv:{CASE}:2", {"channel": "otp"})
    assert (err.value.code, err.value.http_status) == ("verification_unavailable", 503)
    assert q(factory, "select count(*) from identity_verifications")[0][0] == 0


def test_adapter_name_collision_is_a_typed_503(
    client: TestClient, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    to_idv(client)
    monkeypatch.setitem(adapters.ADAPTERS, ADAPTER, object())
    with factory() as s, pytest.raises(CommandError) as err:
        gw(s, "send_verification_request", f"idv:{CASE}:2", {"channel": "otp"})
    assert (err.value.code, err.value.http_status) == ("verification_unavailable", 503)


def test_outbox_refuses_after_expiry_before_the_expirer_runs(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client)
    with factory() as s:
        s.execute(
            text("update identity_verifications set expires_at = sent_at - interval '1 second'")
        )
        s.commit()
    switch(client, Role.CARDHOLDER)
    r = client.get(f"/api/verifications/{vid}/outbox")
    assert r.status_code == 410 and r.json()["code"] == "verification_expired"


def test_expirer_job_expires_due_requests_once(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client)
    later = default_demo_clock().now() + timedelta(hours=1)
    assert identity_mod.verification_expirer(factory, later) == [vid]
    with factory() as s:
        while run_once(s, worker_id="w-test", now=datetime(2031, 1, 1, tzinfo=UTC)) is not None:
            pass
    rows = q(factory, "select status from identity_verifications")
    assert rows == [("expired",)]
    assert q(factory, "select count(*) from audit_events where type='verification.expired'") == [
        (1,)
    ]


def test_demo_expire_requires_staff_or_the_owning_cardholder(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client)
    switch(client, Role.CARDHOLDER)
    missing = client.post("/api/demo/verifications/IDV-NOPE/expire")
    assert missing.status_code == 404 and missing.json()["code"] == "verification_not_found"
    assert client.post(f"/api/demo/verifications/{vid}/expire").status_code == 200


def test_resends_are_capped_with_a_typed_reason(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client)
    with factory() as s:
        s.execute(text("update identity_verifications set sends = 3"))
        s.commit()
    r = command(
        client, "resend_verification_request", f"idv-resend:{vid}:4", {"verification_id": vid}
    )
    assert r.status_code == 409 and r.json()["code"] == "send_limit_reached", r.text


def test_parallel_wrong_submits_never_exceed_three_counted_attempts(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client)
    code = outbox(client, vid)["code"]
    version = view_version(client)
    switch(client, Role.CARDHOLDER)

    def go(n: int) -> int:
        return client.post(
            f"/api/verifications/{vid}/submit_otp",
            json={
                "idempotency_key": f"otp:{vid}:{n}",
                "expected_case_version": version,
                "code": wrong(code),
            },
        ).status_code

    with ThreadPoolExecutor(5) as pool:
        list(pool.map(go, range(1, 6)))
    for n in range(1, 6):  # then keep trying sequentially with fresh versions
        submit(client, vid, wrong(code), n)
    attempts = q(factory, "select attempts from identity_verifications")[0][0]
    counted = q(factory, "select count(*) from verification_attempts")[0][0]
    assert attempts == counted == 3


def test_push_double_answer_is_idempotent(
    client: TestClient, factory: sessionmaker[Session]
) -> None:
    to_idv(client)
    vid = send(client, "push")
    ver = view_version(client)
    switch(client, Role.CARDHOLDER)
    body = {"idempotency_key": f"push:{vid}", "expected_case_version": ver, "approve": True}
    one = client.post(f"/api/verifications/{vid}/answer", json=body)
    two = client.post(f"/api/verifications/{vid}/answer", json=body)
    assert (one.status_code, two.status_code) == (200, 200)
    assert two.json()["status"] == "replayed" and two.json()["result"] == one.json()["result"]
    assert q(factory, "select count(*) from verification_attempts")[0][0] == 1
    flip = client.post(f"/api/verifications/{vid}/answer", json={**body, "approve": False})
    assert flip.status_code == 409  # same key, different answer: key conflict, nothing changes
    assert q(factory, "select status from identity_verifications") == [("verified",)]
