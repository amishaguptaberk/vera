import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from vera_api.graph import TEST_WORKFLOW, build_graph, postgres_checkpointer, run_graph
from vera_api.model_client import ModelResult
from vera_api.runner import SpecialistRunner, create_run
from vera_api.worker import claim_next, enqueue, run_once, touch
from vera_domain.clock import FixedClock
from vera_domain.specialists import ExecutionMode, Finding, SpecialistSpec

T0 = datetime(2026, 11, 10, 17, tzinfo=UTC)
CASE = "CHG-1042"


@pytest.fixture
def factory(client: TestClient, db_url: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(db_url)
    f = sessionmaker(engine, expire_on_commit=False)
    with f() as s:
        s.execute(text("truncate table jobs, workflow_runs cascade"))
        s.execute(text("delete from checkpoint_writes"))
        s.execute(text("delete from checkpoint_blobs"))
        s.execute(text("delete from checkpoints"))
        s.commit()
    yield f
    engine.dispose()


def test_claim_is_exclusive_and_dead_worker_lock_expires(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        enqueue(s, "noop", {"n": 1}, now=T0)
        s.commit()
        job = claim_next(s, "worker-a", T0)
        assert job is not None and job.locked_by == "worker-a" and job.attempts == 1
    with factory() as s2:
        # worker-a "died" holding the lock: not claimable inside the visibility timeout ...
        assert claim_next(s2, "worker-b", T0 + timedelta(minutes=1)) is None
        # ... and claimable after it.
        again = claim_next(s2, "worker-b", T0 + timedelta(minutes=6))
        assert again is not None and again.locked_by == "worker-b" and again.attempts == 2


def test_skip_locked_lets_two_workers_take_different_jobs(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        enqueue(s, "noop", {}, now=T0)
        enqueue(s, "noop", {}, now=T0)
        s.commit()
    a, b = factory(), factory()
    try:
        from sqlalchemy import select
        from vera_api.models_runs import Job

        q = select(Job).where(Job.status == "queued").order_by(Job.id).limit(1)
        first = a.scalars(q.with_for_update(skip_locked=True)).one()
        second = b.scalars(q.with_for_update(skip_locked=True)).one()
        assert first.id != second.id
    finally:
        a.rollback()
        b.rollback()
        a.close()
        b.close()


def test_failed_handler_requeues_then_succeeds(factory: sessionmaker[Session]) -> None:
    calls: list[int] = []

    def flaky(session: Session, payload: dict[str, Any], touch: Callable[[], bool]) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    with factory() as s:
        jid = enqueue(s, "flaky", {}, now=T0)
        s.commit()
        assert run_once(s, worker_id="w", now=T0, handlers={"flaky": flaky}) == jid
        status = s.execute(text(f"select status, last_error from jobs where id={jid}")).one()
        assert status[0] == "queued" and "boom" in status[1]
        assert run_once(s, worker_id="w", now=T0, handlers={"flaky": flaky}) is None  # backoff
        later = T0 + timedelta(minutes=1)
        assert run_once(s, worker_id="w", now=later, handlers={"flaky": flaky}) == jid
        assert s.execute(text(f"select status from jobs where id={jid}")).scalar_one() == "done"


class Out(BaseModel):
    findings: list[Finding]


class In(BaseModel):
    case_id: str


SPEC = SpecialistSpec(
    name="echo-check",
    prompt_version="v1",
    input_schema=In,
    output_schema=Out,
    allowed_record_ids=lambda case_id: frozenset({case_id}),
)


class CountingClient:
    calls = 0

    def complete(self, **kw: Any) -> ModelResult:
        CountingClient.calls += 1
        f = {"record_id": CASE, "version": 3, "field": "amount", "value": "2,480.00"}
        return ModelResult({"findings": [f]}, [], {}, "stub", ExecutionMode.REPLAY)


def test_graph_runs_parallel_nodes_then_join(db_url: str) -> None:
    order: list[str] = []
    lock = threading.Lock()

    def node(key: str, kind: str, state: dict[str, Any]) -> None:
        with lock:
            order.append(key)

    with postgres_checkpointer(db_url) as saver:
        out = run_graph(build_graph(TEST_WORKFLOW, node, saver), "run_graph_basic")
    assert sorted(order[:2]) == ["charge", "related"] and order[2] == "review"
    assert sorted(out["completed"]) == ["charge", "related", "review"]


def test_worker_crash_resumes_from_checkpoint_without_duplicates(
    factory: sessionmaker[Session], db_url: str
) -> None:
    CountingClient.calls = 0
    runner = SpecialistRunner(
        lambda m, c: CountingClient(), lambda r, f: ("2,480.00", 3), FixedClock(T0)
    )
    with factory() as s:
        run_id = create_run(s, case_id=CASE, mode=ExecutionMode.REPLAY, now=T0)
    node_calls: dict[str, int] = {}
    crash = {"armed": True}

    def node(key: str, kind: str, state: dict[str, Any]) -> None:
        node_calls[key] = node_calls.get(key, 0) + 1
        if kind == "join" and crash["armed"]:
            crash["armed"] = False
            raise SystemError("worker killed between nodes")
        with factory() as own:  # parallel nodes must not share a session
            runner.run_step(own, run_id, key, SPEC, {"case_id": CASE}, ExecutionMode.REPLAY)

    def handler(session: Session, payload: dict[str, Any], touch: Callable[[], bool]) -> None:
        with postgres_checkpointer(db_url) as saver:
            run_graph(build_graph(TEST_WORKFLOW, node, saver), payload["run_id"])

    with factory() as s:
        enqueue(s, "run_graph", {"run_id": run_id}, now=T0)
        s.commit()
        handlers = {"run_graph": handler}
        run_once(s, worker_id="w1", now=T0, handlers=handlers)  # crashes at the join
        assert node_calls == {"charge": 1, "related": 1, "review": 1}
        run_once(s, worker_id="w2", now=T0 + timedelta(minutes=1), handlers=handlers)  # restart

        assert node_calls == {"charge": 1, "related": 1, "review": 2}  # no completed node re-ran
        assert CountingClient.calls == 3
        steps = (
            s.execute(
                text("select step_key from workflow_steps where run_id=:r order by 1"),
                {"r": run_id},
            )
            .scalars()
            .all()
        )
        assert steps == ["charge", "related", "review"]
        evs = (
            s.execute(
                text("select detail->>'step_key' from audit_events where type='run.step_started'")
            )
            .scalars()
            .all()
        )
        assert sorted(evs) == ["charge", "related", "review"]
        done = s.execute(text("select count(*) from audit_events where type='run.step_succeeded'"))
        assert done.scalar_one() == 3
        assert s.execute(text("select status from jobs")).scalar_one() == "done"


def test_touched_job_is_not_reclaimed_after_the_visibility_timeout(
    factory: sessionmaker[Session],
) -> None:
    with factory() as s:
        jid = enqueue(s, "noop", {}, now=T0)
        s.commit()
        assert claim_next(s, "worker-a", T0) is not None
        assert touch(s.get_bind(), jid, "worker-b", T0 + timedelta(minutes=4)) is False
        assert touch(s.get_bind(), jid, "worker-a", T0 + timedelta(minutes=4)) is True
    with factory() as s2:
        assert claim_next(s2, "worker-b", T0 + timedelta(minutes=6)) is None  # heartbeat held it
        again = claim_next(s2, "worker-b", T0 + timedelta(minutes=10))
        assert again is not None and again.locked_by == "worker-b"


def test_run_once_hands_the_handler_a_heartbeat_for_its_job(
    factory: sessionmaker[Session], db_url: str
) -> None:
    seen: list[Any] = []
    later = T0 + timedelta(minutes=4)

    def slow(session: Session, payload: dict[str, Any], touch: Callable[[], bool]) -> None:
        assert touch() is True
        engine = create_engine(db_url)  # another worker's view, outside this transaction
        with engine.connect() as conn:
            seen.append(conn.execute(text("select locked_at from jobs")).scalar_one())
        engine.dispose()

    with factory() as s:
        enqueue(s, "slow", {}, now=T0)
        s.commit()
        run_once(s, worker_id="w", now=T0, handlers={"slow": slow}, clock=lambda: later)
    assert seen == [later]
