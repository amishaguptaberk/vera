import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api.model_client import (
    LiveModelClient,
    ModelClient,
    ModelError,
    ModelResult,
    RecordedModelClient,
)
from vera_api.models_runs import WorkflowStep
from vera_api.runner import SpecialistRunner, create_run
from vera_domain.clock import FixedClock
from vera_domain.specialists import ExecutionMode, Finding, SpecialistSpec

CASE = "CHG-1042"
KEY = "nvapi-STUB-SECRET-KEY-123"
RECORDINGS = Path(__file__).parent.parent / "fixtures" / "recordings"
SOURCE: dict[tuple[str, str], tuple[Any, int]] = {
    (CASE, "amount"): ("2,480.00", 3),
    (CASE, "quantity"): (10, 3),
    ("CHG-9999", "amount"): ("1.00", 1),
}


class EchoIn(BaseModel):
    case_id: str


class EchoOut(BaseModel):
    findings: list[Finding]
    summary: str


SPEC = SpecialistSpec(
    name="echo-check",
    prompt_version="v1",
    input_schema=EchoIn,
    output_schema=EchoOut,
    allowed_record_ids=lambda case_id: frozenset({case_id}),
)


def read_field(record_id: str, field: str) -> tuple[Any, int]:
    return SOURCE[(record_id, field)]


def out(value: str = "2,480.00", record: str = CASE) -> dict[str, Any]:
    return {
        "findings": [
            {"record_id": record, "version": 3, "field": "amount", "value": value, "statement": "s"}
        ],
        "summary": "done",
    }


def result(content: dict[str, Any], tool_calls: list[dict[str, Any]] | None = None) -> ModelResult:
    return ModelResult(
        content=content,
        tool_calls=tool_calls or [],
        usage={"total_tokens": 10},
        model_id="stub-model",
        mode=ExecutionMode.LIVE,
    )


class ScriptedClient:
    """A ModelClient double that serves a fixed script and records what it was asked."""

    def __init__(self, script: list[ModelResult | ModelError]) -> None:
        self.script = list(script)
        self.calls: list[list[dict[str, Any]]] = []

    def complete(self, **kw: Any) -> ModelResult:
        self.calls.append(list(kw["messages"]))
        item = self.script.pop(0)
        if isinstance(item, ModelError):
            raise item
        return item


@pytest.fixture
def session(client: TestClient, db_url: str) -> Iterator[Session]:  # client resets the DB
    engine = create_engine(db_url)
    with sessionmaker(engine, expire_on_commit=False)() as s:
        s.execute(text("truncate table jobs"))
        s.commit()
        yield s
    engine.dispose()


def make_runner(
    factory: Callable[[ExecutionMode, str], ModelClient],
) -> SpecialistRunner:
    return SpecialistRunner(factory, read_field, FixedClock(datetime(2026, 11, 10, 17, tzinfo=UTC)))


def new_run(session: Session, mode: ExecutionMode = ExecutionMode.REPLAY) -> str:
    return create_run(session, case_id=CASE, mode=mode, now=datetime(2026, 11, 10, tzinfo=UTC))


def step_row(session: Session, run_id: str, key: str = "s1") -> WorkflowStep:
    session.expire_all()
    return session.scalars(
        select(WorkflowStep).where(WorkflowStep.run_id == run_id, WorkflowStep.step_key == key)
    ).one()


def events(session: Session) -> list[str]:
    rows = session.execute(text("select type from audit_events order by id")).scalars()
    return [t for t in rows if t.startswith("run.")]


def test_ungrounded_twice_fails_step_with_three_calls_and_no_apply(session: Session) -> None:
    run_id = new_run(session, ExecutionMode.LIVE)
    bad = out("2,840.00")
    stub = ScriptedClient([result(bad), result(bad), result(bad)])
    applied: list[BaseModel] = []

    outcome = make_runner(lambda m, c: stub).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.LIVE, applied.append
    )

    assert len(stub.calls) == 3 and applied == []
    assert outcome.status == "failed" and outcome.failure_reason == "ungrounded"
    row = step_row(session, run_id)
    assert (row.status, row.failure_reason, row.attempts) == ("failed", "ungrounded", 3)
    assert row.execution_mode == "live" and row.output is None
    assert "2,840.00" in (row.error or "")
    assert events(session) == ["run.step_started", "run.step_failed"]


def test_validation_errors_are_fed_back_then_success_applies_typed_output(
    session: Session,
) -> None:
    run_id = new_run(session)
    stub = ScriptedClient([result(out("2,840.00")), result(out())])
    applied: list[BaseModel] = []
    outcome = make_runner(lambda m, c: stub).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY, applied.append
    )
    assert outcome.status == "succeeded"
    assert len(stub.calls) == 2
    assert "2,840.00" in json.dumps(stub.calls[1])  # validator error reached the model
    [typed] = applied
    assert isinstance(typed, EchoOut) and typed.findings[0].value == "2,480.00"
    row = step_row(session, run_id)
    assert row.status == "succeeded" and row.attempts == 2 and row.model_id == "stub-model"
    assert row.prompt_version == "v1" and row.usage == {"total_tokens": 20}
    assert row.output is not None and row.output["summary"] == "done"
    assert events(session) == ["run.step_started", "run.step_succeeded"]


def test_schema_invalid_after_retries(session: Session) -> None:
    run_id = new_run(session)
    stub = ScriptedClient([result({"nope": 1})] * 3)
    outcome = make_runner(lambda m, c: stub).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY
    )
    assert outcome.failure_reason == "schema_invalid" and len(stub.calls) == 3


def test_tool_call_outside_scope_is_scope_violation_recorded_on_step(session: Session) -> None:
    run_id = new_run(session)
    call = {
        "id": "1",
        "name": "read_field",
        "arguments": {"record_id": "CHG-9999", "field": "amount"},
    }
    stub = ScriptedClient([result({}, [call])])
    applied: list[BaseModel] = []
    outcome = make_runner(lambda m, c: stub).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY, applied.append
    )
    assert outcome.failure_reason == "scope_violation" and applied == []
    row = step_row(session, run_id)
    assert row.status == "failed" and row.failure_reason == "scope_violation"
    [rec] = row.tool_calls
    assert rec["outcome"] == "scope_violation" and rec["record_id"] == "CHG-9999"
    assert len(stub.calls) == 1  # no validation retry after a scope violation


def test_in_scope_tool_call_is_executed_and_result_returned_to_model(session: Session) -> None:
    run_id = new_run(session)
    call = {"id": "1", "name": "read_field", "arguments": {"record_id": CASE, "field": "amount"}}
    stub = ScriptedClient([result({}, [call]), result(out())])
    outcome = make_runner(lambda m, c: stub).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY
    )
    assert outcome.status == "succeeded"
    assert "2,480.00" in json.dumps(stub.calls[1])
    assert step_row(session, run_id).tool_calls[0]["outcome"] == "ok"


def test_live_failure_is_never_replaced_by_a_recording_until_explicit_replay_retry(
    session: Session,
) -> None:
    run_id = new_run(session, ExecutionMode.LIVE)
    asked: list[ExecutionMode] = []
    live = ScriptedClient([ModelError("provider_error", "HTTP 503")])

    def factory(mode: ExecutionMode, case_id: str) -> ModelClient:
        asked.append(mode)
        return (
            live if mode is ExecutionMode.LIVE else RecordedModelClient(RECORDINGS, case_id=case_id)
        )

    runner = make_runner(factory)
    first = runner.run_step(session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.LIVE)
    assert first.status == "failed" and first.failure_reason == "provider_error"
    assert asked == [ExecutionMode.LIVE]  # no recording was consulted
    row = step_row(session, run_id)
    assert (row.status, row.execution_mode) == ("failed", "live")

    applied: list[BaseModel] = []
    second = runner.run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY, applied.append
    )
    assert second.status == "succeeded" and len(applied) == 1
    row = step_row(session, run_id)
    assert (row.status, row.execution_mode, row.model_id) == (
        "succeeded",
        "replay",
        "recorded-stub-model",
    )
    assert row.failure_reason is None and row.attempts == 1


def test_missing_recording_in_replay_is_an_error(session: Session, tmp_path: Path) -> None:
    run_id = new_run(session)
    runner = make_runner(lambda m, c: RecordedModelClient(tmp_path, case_id=c))
    outcome = runner.run_step(session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY)
    assert outcome.status == "failed" and outcome.failure_reason == "missing_recording"
    assert step_row(session, run_id).failure_reason == "missing_recording"


def test_succeeded_step_is_not_rerun(session: Session) -> None:
    run_id = new_run(session)
    stub = ScriptedClient([result(out())])
    runner = make_runner(lambda m, c: stub)
    applied: list[BaseModel] = []
    for _ in range(2):
        outcome = runner.run_step(
            session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY, applied.append
        )
        assert outcome.status == "succeeded"
    assert len(stub.calls) == 1 and len(applied) == 1
    assert events(session) == ["run.step_started", "run.step_succeeded"]


def test_runner_writes_no_case_state(session: Session) -> None:
    snapshot = """select
      (select count(*) from state_transitions), (select count(*) from claims),
      (select count(*) from reports), (select count(*) from case_assignments),
      (select case_version::text || state || step from cases where id = 'CHG-1042')"""
    run_id = new_run(session)
    before = tuple(session.execute(text(snapshot)).one())
    make_runner(lambda m, c: ScriptedClient([result(out())])).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY
    )
    assert tuple(session.execute(text(snapshot)).one()) == before


def live_client(handler: Callable[[httpx.Request], httpx.Response]) -> LiveModelClient:
    return LiveModelClient(
        base_url="http://stub/v1",
        model_id="stub-model",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
    )


def test_live_missing_key_fails_explicitly_and_key_never_stored(
    session: Session, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    ok = live_client(lambda r: httpx.Response(200, json={}))
    run_id = new_run(session, ExecutionMode.LIVE)
    runner = make_runner(lambda m, c: ok)
    o = runner.run_step(session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.LIVE)
    assert o.failure_reason == "provider_error"
    assert "NVIDIA_API_KEY" in (step_row(session, run_id).error or "")

    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    echo_key = live_client(lambda r: httpx.Response(500, text=f"boom {KEY}"))
    run2 = new_run(session, ExecutionMode.LIVE)
    make_runner(lambda m, c: echo_key).run_step(
        session, run2, "s1", SPEC, {"case_id": CASE}, ExecutionMode.LIVE
    )
    good = live_client(
        lambda r: httpx.Response(
            200, json={"model": "m", "choices": [{"message": {"content": json.dumps(out())}}]}
        )
    )
    run3 = new_run(session, ExecutionMode.LIVE)
    make_runner(lambda m, c: good).run_step(
        session, run3, "s1", SPEC, {"case_id": CASE}, ExecutionMode.LIVE
    )
    assert step_row(session, run3).status == "succeeded"
    dump = session.execute(
        text(
            "select (select string_agg(t::text, ' ') from workflow_steps t) || "
            "(select string_agg(a::text, ' ') from audit_events a)"
        )
    ).scalar_one()
    assert KEY not in dump and KEY not in caplog.text


def test_runs_endpoint_lists_steps_with_mode_model_prompt_usage(
    client: TestClient, session: Session
) -> None:
    run_id = new_run(session)
    make_runner(lambda m, c: ScriptedClient([result(out())])).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY
    )
    resp = client.get(f"/api/cases/{CASE}/runs")
    assert resp.status_code == 200
    [run] = resp.json()
    assert run["id"] == run_id and run["mode"] == "replay"
    [step] = run["steps"]
    assert step["step_key"] == "s1" and step["status"] == "succeeded"
    assert step["execution_mode"] == "replay" and step["model_id"] == "stub-model"
    assert step["prompt_version"] == "v1" and step["usage"] == {"total_tokens": 10}
    assert step["failure_reason"] is None
    assert client.get("/api/cases/NOPE/runs").status_code == 404


def test_live_tool_round_trip_uses_openai_wire_format(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)
    bodies: list[dict[str, Any]] = []
    tool_call = {
        "id": "call_7",
        "type": "function",
        "function": {
            "name": "read_field",
            "arguments": json.dumps({"record_id": CASE, "field": "amount"}),
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        message: dict[str, Any] = (
            {"role": "assistant", "content": None, "tool_calls": [tool_call]}
            if len(bodies) == 1
            else {"role": "assistant", "content": json.dumps(out())}
        )
        return httpx.Response(200, json={"model": "m", "choices": [{"message": message}]})

    client = live_client(handler)
    run_id = new_run(session, ExecutionMode.LIVE)
    outcome = make_runner(lambda m, c: client).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.LIVE
    )
    assert outcome.status == "succeeded" and len(bodies) == 2
    msgs = bodies[1]["messages"]
    i = next(n for n, m in enumerate(msgs) if m.get("tool_calls"))
    assistant, tool = msgs[i], msgs[i + 1]
    [sent] = assistant["tool_calls"]
    assert sent["id"] == "call_7" and sent["type"] == "function"
    assert sent["function"]["name"] == "read_field"
    assert isinstance(sent["function"]["arguments"], str)
    assert json.loads(sent["function"]["arguments"]) == {"record_id": CASE, "field": "amount"}
    assert tool["role"] == "tool" and tool["tool_call_id"] == "call_7"
    assert isinstance(tool["content"], str) and "2,480.00" in tool["content"]


def test_step_finished_by_another_worker_meanwhile_is_not_applied_twice(
    session: Session, db_url: str
) -> None:
    run_id = new_run(session)
    other = create_engine(db_url)

    class OtherWorkerWins:
        def complete(self, **kw: Any) -> ModelResult:
            # While this worker waits on the model, another worker finishes the same step.
            with other.begin() as conn:
                conn.execute(
                    text(
                        "update workflow_steps set status='succeeded', attempts=1, output=:o"
                        " where run_id=:r and step_key='s1'"
                    ),
                    {"o": json.dumps(out("2,480.00")), "r": run_id},
                )
            return result(out())

    applied: list[BaseModel] = []
    outcome = make_runner(lambda m, c: OtherWorkerWins()).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY, applied.append
    )
    other.dispose()
    assert outcome.status == "succeeded" and outcome.attempts == 1
    assert isinstance(outcome.output, EchoOut) and outcome.output.summary == "done"
    assert applied == []
    assert events(session) == ["run.step_started"]  # no second run.step_succeeded from us


def test_heartbeat_is_called_before_each_model_call(session: Session) -> None:
    run_id = new_run(session)
    call = {"id": "1", "name": "read_field", "arguments": {"record_id": CASE, "field": "amount"}}
    beats: list[int] = []
    stub = ScriptedClient([result({}, [call]), result(out())])

    def beat() -> None:
        beats.append(len(stub.calls))  # model calls made so far when the heartbeat fires

    outcome = make_runner(lambda m, c: stub).run_step(
        session, run_id, "s1", SPEC, {"case_id": CASE}, ExecutionMode.REPLAY, heartbeat=beat
    )
    assert outcome.status == "succeeded"
    assert beats == [0, 1]
