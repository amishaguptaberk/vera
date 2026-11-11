"""Postgres-backed job worker (plan §12): FOR UPDATE SKIP LOCKED, no Redis.

A job locked by a worker that died becomes claimable again after the visibility timeout.
Handlers must be idempotent per (run_id, step_key): the runner skips succeeded steps and the
graph resumes from its checkpoint, so a re-delivered job repeats no completed effect.
"""

import os
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from vera_api.config import Settings
from vera_api.db import make_engine
from vera_api.models_runs import Job

Handler = Callable[[Session, dict[str, Any]], None]
HANDLERS: dict[str, Handler] = {}

VISIBILITY_TIMEOUT = timedelta(minutes=5)
MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(seconds=5)


def register(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(
    session: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    run_after: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    job = Job(
        kind=kind, payload=payload, status="queued", run_after=run_after or now, created_at=now
    )
    session.add(job)
    session.flush()
    return job.id


def claim_next(
    session: Session,
    worker_id: str,
    now: datetime,
    visibility_timeout: timedelta = VISIBILITY_TIMEOUT,
) -> Job | None:
    """Lock the next runnable job: queued and due, or running under a dead worker's stale lock."""
    job = session.scalars(
        select(Job)
        .where(
            or_(
                (Job.status == "queued") & (Job.run_after <= now),
                (Job.status == "running") & (Job.locked_at <= now - visibility_timeout),
            )
        )
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        return None
    job.status = "running"
    job.locked_by = worker_id
    job.locked_at = now
    job.attempts += 1
    session.commit()
    return job


def run_once(
    session: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    handlers: dict[str, Handler] | None = None,
    visibility_timeout: timedelta = VISIBILITY_TIMEOUT,
) -> int | None:
    """Claim and run one job; returns its id, or None when nothing is runnable."""
    now = now or datetime.now(UTC)
    handlers = HANDLERS if handlers is None else handlers
    job = claim_next(session, worker_id, now, visibility_timeout)
    if job is None:
        return None
    job_id, kind, payload, attempts = job.id, job.kind, dict(job.payload), job.attempts
    try:
        handler = handlers[kind]
        handler(session, payload)
    except Exception as exc:  # the job is retried or failed; never swallowed silently
        session.rollback()
        job = session.get(Job, job_id)
        assert job is not None
        job.last_error = f"{type(exc).__name__}: {exc}"[:500]
        job.locked_by = None
        job.locked_at = None
        if attempts >= MAX_ATTEMPTS or kind not in handlers:
            job.status = "failed"
        else:
            job.status = "queued"
            job.run_after = now + RETRY_DELAY
        session.commit()
        return job_id
    session.rollback()  # drop any stale transaction state before the final write
    job = session.get(Job, job_id)
    assert job is not None
    job.status = "done"
    job.locked_by = None
    job.locked_at = None
    session.commit()
    return job_id


def main() -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    factory = sessionmaker(make_engine(Settings().database_url), expire_on_commit=False)
    while True:
        with factory() as session:
            ran = run_once(session, worker_id=worker_id)
        if ran is None:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
