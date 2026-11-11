"""Extension seams against real Postgres: adapters, fact providers, effects, approval gate."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api import adapters, gateway, plugins
from vera_api.auth import Actor
from vera_api.models import Case
from vera_domain.adapters import AdapterResult, SimulatedAdapter
from vera_domain.clock import default_demo_clock
from vera_domain.commands import (
    REGISTRY,
    ApprovalState,
    CommandSpec,
    NoPayload,
    StepSet,
    reduce_open,
)
from vera_domain.enums import CaseStep, EventType, Role
from vera_domain.errors import CommandError

CASE = "CHG-1042"
NOW = default_demo_clock().now()
ANALYST = Actor("usr-sam-rivera", "Sam Rivera", Role.ANALYST, frozenset({Role.ANALYST}))


class Echo:
    """Test-only adapter: returns the request and counts real calls."""

    def __init__(self) -> None:
        self.calls = 0

    def call(self, operation: str, request: dict[str, Any]) -> AdapterResult:
        self.calls += 1
        return AdapterResult(status="succeeded", result={"echo": request, "op": operation})


@pytest.fixture
def db(client: TestClient, db_url: str) -> Iterator[Session]:
    engine = create_engine(db_url)
    with sessionmaker(engine)() as s:
        yield s
    engine.dispose()


@pytest.fixture
def echo(monkeypatch: pytest.MonkeyPatch) -> Echo:
    adapter = Echo()
    monkeypatch.setitem(adapters.ADAPTERS, "echo", adapter)
    return adapter


def run(db: Session, key: str = "echo:1", request: dict[str, Any] | None = None) -> AdapterResult:
    return adapters.execute(
        db,
        case_id=CASE,
        adapter="echo",
        operation="say",
        key=key,
        request=request or {"n": 1},
        now=NOW,
    )


def events(db: Session) -> list[str]:
    rows = db.execute(text("select type from audit_events where type like 'adapter.%' order by id"))
    return [r[0] for r in rows]


def test_registered_adapters_are_simulated_and_declared_by_feature_modules() -> None:
    """Features register their simulated adapters at import; test adapters never leak."""
    assert "echo" not in adapters.ADAPTERS
    for name, adapter in adapters.ADAPTERS.items():
        assert isinstance(adapter, SimulatedAdapter), name
        assert type(adapter).__module__ in plugins.FEATURES, (name, type(adapter).__module__)


def test_registering_an_adapter_name_twice_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapters, "ADAPTERS", dict(adapters.ADAPTERS))
    adapters.register_adapter("t_once", Echo())
    with pytest.raises(ValueError, match="already registered"):
        adapters.register_adapter("t_once", Echo())


def test_execute_is_exactly_once_by_key_and_replays_the_stored_result(
    db: Session, echo: Echo
) -> None:
    first = run(db)
    again = run(db)
    assert first.status == "succeeded" and first.result == {"echo": {"n": 1}, "op": "say"}
    assert (again.result, again.execution_id, again.replayed) == (
        first.result,
        first.execution_id,
        True,
    )
    assert echo.calls == 1
    assert events(db) == ["adapter.succeeded"]
    with pytest.raises(CommandError) as err:
        run(db, request={"n": 2})
    assert err.value.code == "idempotency_key_conflict"


def test_unregistered_adapter_is_a_typed_error(db: Session) -> None:
    with pytest.raises(CommandError) as err:
        run(db)
    assert err.value.code == "adapter_not_registered"


def test_uncertain_hides_the_result_until_lookup_resolves_it(db: Session, echo: Echo) -> None:
    adapters.inject_fault(db, "echo", "say", "uncertain", 1)
    out = run(db)
    assert (out.status, out.result) == ("uncertain", {})
    assert run(db).status == "uncertain" and echo.calls == 1  # never dispatched twice
    resolved = adapters.lookup(db, "echo:1", NOW)
    assert resolved is not None and resolved.status == "succeeded"
    assert resolved.result == {"echo": {"n": 1}, "op": "say"}
    assert run(db).status == "succeeded" and echo.calls == 1
    assert events(db) == ["adapter.uncertain", "adapter.succeeded"]
    assert adapters.lookup(db, "missing") is None


@pytest.mark.parametrize("mode", ["fail", "timeout"])
def test_fault_is_consumed_n_times_then_the_same_key_succeeds(
    db: Session, echo: Echo, mode: str
) -> None:
    adapters.inject_fault(db, "echo", "say", mode, 2)  # type: ignore[arg-type]
    assert [run(db).status for _ in range(3)] == ["failed", "failed", "succeeded"]
    assert echo.calls == 1  # failed before the effect: the adapter was not called
    assert db.execute(text("select attempts from adapter_executions")).scalar_one() == 3
    assert db.execute(text("select remaining from adapter_faults")).scalar_one() == 0


def test_adapter_fault_endpoint_and_reset_clear_feature_tables(
    client: TestClient, db: Session, echo: Echo
) -> None:
    body = {"adapter": "echo", "operation": "say", "mode": "fail", "times": 1}
    assert client.post("/api/demo/adapter-fault", json=body).status_code == 200
    assert (
        client.post("/api/demo/adapter-fault", json={**body, "adapter": "nope"}).status_code == 422
    )
    assert run(db).status == "failed"
    db.commit()
    assert client.post("/api/demo/reset").status_code == 200
    assert db.execute(text("select count(*) from adapter_executions")).scalar_one() == 0
    assert db.execute(text("select count(*) from adapter_faults")).scalar_one() == 0


def test_adapter_fault_endpoint_is_not_mounted_outside_synthetic(db_url: str) -> None:
    from vera_api.app import create_app
    from vera_api.config import Settings

    app = create_app(Settings(database_url=db_url, env="production", session_secret="x" * 40))
    paths = set(app.openapi()["paths"])
    assert "/api/demo/adapter-fault" not in paths and "/api/cases" in paths


def test_emit_rejects_an_unregistered_event_type(db: Session) -> None:
    from vera_api.intake import _emit

    case = db.get(Case, CASE)
    assert case is not None
    with pytest.raises(ValueError, match="not registered"):
        _emit(db, "nope.never", case, "u", Role.SYSTEM, NOW, [], "x")


# --- fact providers ---


def test_facts_for_merges_providers_and_rejects_duplicates(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = db.get(Case, CASE)
    assert case is not None
    assert gateway.facts_for(db, case).investigation_run_status == "none"
    assert gateway.facts_with_runs is gateway.facts_for
    assert gateway._investigation_facts in gateway.FACT_PROVIDERS
    # Features may own followup_status once loaded: start from the built-in provider only.
    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [gateway._investigation_facts])

    def followup(session: Session, c: Case) -> dict[str, Any]:
        return {"followup_status": "sent"}

    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [*gateway.FACT_PROVIDERS, followup])
    assert gateway.facts_for(db, case).followup_status == "sent"
    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [*gateway.FACT_PROVIDERS, followup])
    with pytest.raises(RuntimeError, match="duplicate fact .followup_status."):
        gateway.facts_for(db, case)
    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [lambda s, c: {"followup_status": "bogus"}])
    with pytest.raises(ValueError):
        gateway.facts_for(db, case)


# --- plug-in command with effect, after-effect, provider-driven step, approval gate ---


def execute(db: Session, command: str, key: str) -> gateway.Outcome:
    case = db.get(Case, CASE)
    assert case is not None
    db.refresh(case)
    return gateway.execute_command(
        db,
        now=NOW,
        case_id=CASE,
        command=command,
        key=key,
        expected_version=case.case_version,
        payload={},
        actor=ANALYST,
        request_id="t",
    )


def plug(monkeypatch: pytest.MonkeyPatch, name: str, **kw: Any) -> CommandSpec:
    spec = CommandSpec(
        name,
        frozenset({Role.ANALYST}),
        NoPayload,
        StepSet(),
        name + ":{case_id}:{case_version}",
        reduce_open,
        (EventType.CASE_OPENED,),
        "Plugged action",
        "primary",
        **kw,
    )
    monkeypatch.setitem(REGISTRY, name, spec)
    return spec


def test_plugged_command_runs_effect_before_reducer_and_after_effect_after_event(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    plug(monkeypatch, "t_plugged")
    seen: list[Any] = []

    def effect(s: Session, case: Case, actor: Actor, p: Any, now: Any, ctx: Any) -> dict[str, Any]:
        seen.append(("effect", actor.user_id, ctx.command, ctx.key, case.case_version))
        return {"sent": True}

    def after(s: Session, case: Case, actor: Actor, p: Any, now: Any, ctx: Any, out: Any) -> None:
        seen.append(("after", ctx.extra, out.event_ids, case.case_version))

    def provider(s: Session, case: Case) -> dict[str, Any]:
        return {"followup_status": "sent"} if seen else {}

    monkeypatch.setitem(gateway.EFFECTS, "t_plugged", effect)
    monkeypatch.setitem(gateway.AFTER_EFFECTS, "t_plugged", after)
    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [gateway._investigation_facts, provider])
    out = execute(db, "t_plugged", f"t_plugged:{CASE}:1")
    assert seen[0] == ("effect", "usr-sam-rivera", "t_plugged", f"t_plugged:{CASE}:1", 1)
    assert seen[1] == ("after", {"sent": True}, out.event_ids, 2)
    case = db.get(Case, CASE)
    assert case is not None
    db.refresh(case)
    # The step comes from the provider's stored fact through derive_step, not from the command.
    assert (case.state, case.step) == ("waiting_on_cardholder", CaseStep.WAITING.value)


def test_register_commands_rejects_duplicates_and_foreign_handlers() -> None:
    with pytest.raises(ValueError, match="already registered"):
        gateway.register_commands("feat", human={"open_case": REGISTRY["open_case"]})
    with pytest.raises(ValueError, match="not one of its commands"):
        gateway.register_commands("feat", effects={"open_case": lambda *a: {}})
    assert {"link_report", "evaluate_policy", "append_evidence_version"} <= set(gateway.EFFECTS)
    assert "vera_api.adapters" in plugins.FEATURES


def bound(case: Case, **kw: Any) -> ApprovalState:
    base: dict[str, Any] = {
        "approval_id": "APR-1",
        "status": "approved",
        "snapshot_hash": case.evidence_snapshot,
        "policy_version": case.policy_version,
        "workflow_version": case.workflow_version,
        "transaction_id": case.transaction_id,
    }
    return ApprovalState(**{**base, **kw})


def blocked_reason(client: TestClient, command: str) -> str | None:
    view = client.get(f"/api/cases/{CASE}").json()
    return next((b["reason"] for b in view["blocked_actions"] if b["command"] == command), None)


def test_requires_approval_blocks_without_a_provider_and_writes_nothing(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    plug(monkeypatch, "t_approved", requires_approval=True)
    monkeypatch.setattr(gateway, "APPROVAL_PROVIDER", None)  # a feature may have registered one
    with pytest.raises(CommandError) as err:
        execute(db, "t_approved", f"t_approved:{CASE}:1")
    assert (err.value.code, err.value.http_status) == ("approval_required", 422)
    assert err.value.blocked_reason == "No approval recorded"
    assert blocked_reason(client, "t_approved") == "No approval recorded"
    assert db.execute(text("select case_version from cases where id=:i"), {"i": CASE}).scalar() == 1


@pytest.mark.parametrize(
    ("change", "code", "status"),
    [
        ({"status": "requested"}, "approval_required", 422),
        ({"status": "stale"}, "approval_stale", 409),
        ({"snapshot_hash": "sha256:old"}, "approval_stale", 409),
        ({"policy_version": 99}, "approval_stale", 409),
        ({"workflow_version": 99}, "approval_stale", 409),
        ({"transaction_id": "txn-other"}, "approval_stale", 409),
    ],
)
def test_requires_approval_rejects_unapproved_stale_or_unbound(
    client: TestClient,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
    code: str,
    status: int,
) -> None:
    plug(monkeypatch, "t_approved", requires_approval=True)
    monkeypatch.setattr(gateway, "APPROVAL_PROVIDER", lambda s, c: bound(c, **change))
    with pytest.raises(CommandError) as err:
        execute(db, "t_approved", f"t_approved:{CASE}:1")
    assert (err.value.code, err.value.http_status) == (code, status)
    assert blocked_reason(client, "t_approved") == err.value.blocked_reason


def test_requires_approval_passes_with_an_approval_bound_to_the_current_pins(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    plug(monkeypatch, "t_approved", requires_approval=True)
    monkeypatch.setattr(gateway, "APPROVAL_PROVIDER", lambda s, c: bound(c))
    assert blocked_reason(client, "t_approved") is None
    assert execute(db, "t_approved", f"t_approved:{CASE}:1").status == "recorded"


@pytest.mark.parametrize(
    "override",
    [{"closed": False}, {"hold": None}, {"opened_at": None}, {"owner_id": "x"}, {"due_at": None}],
)
def test_a_provider_cannot_override_the_case_rows_own_facts(
    db: Session, monkeypatch: pytest.MonkeyPatch, override: dict[str, Any]
) -> None:
    case = db.get(Case, CASE)
    assert case is not None
    case.state, case.step = "closed", "closed"
    case.hold = {
        "reason": "waiting",
        "next_owner_id": "u",
        "held_by": "u",
        "held_at": NOW.isoformat(),
    }
    assert gateway.facts_for(db, case).closed and gateway.facts_for(db, case).hold is not None
    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [*gateway.FACT_PROVIDERS, lambda s, c: override])
    with pytest.raises(RuntimeError, match="reserved"):
        gateway.facts_for(db, case)
    db.rollback()


def test_a_provider_cannot_return_an_unknown_fact(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = db.get(Case, CASE)
    assert case is not None
    monkeypatch.setattr(gateway, "FACT_PROVIDERS", [lambda s, c: {"not_a_fact": 1}])
    with pytest.raises(RuntimeError, match="unknown"):
        gateway.facts_for(db, case)


def test_concurrent_first_calls_with_one_key_dispatch_once_and_both_replay(
    client: TestClient, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading
    import time

    class Slow(Echo):
        def call(self, operation: str, request: dict[str, Any]) -> AdapterResult:
            time.sleep(0.3)
            return super().call(operation, request)

    slow = Slow()
    monkeypatch.setitem(adapters.ADAPTERS, "echo", slow)
    engine = create_engine(db_url)
    barrier = threading.Barrier(2)
    results: list[Any] = []

    def worker() -> None:
        with sessionmaker(engine)() as s:
            barrier.wait()
            try:
                out = run(s, key="echo:race")
                s.commit()
                results.append((out.status, out.result, out.execution_id))
            except Exception as exc:  # noqa: BLE001
                results.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    engine.dispose()
    assert slow.calls == 1
    assert len(results) == 2 and results[0] == results[1], results
    assert results[0][0] == "succeeded"
