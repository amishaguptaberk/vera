"""`python -m vera_api.worker` must run the imported module's main (where features register)."""

import runpy
import sys

import pytest
from vera_api import worker


def test_running_as_main_delegates_to_the_imported_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(worker, "main", lambda: calls.append("imported"))
    monkeypatch.setitem(sys.modules, "vera_api.worker", worker)
    runpy.run_module("vera_api.worker", run_name="__main__")
    assert calls == ["imported"]


def test_the_worker_process_registers_every_job_kind_the_api_enqueues() -> None:
    """A fresh worker process (as `python -m vera_api.worker` starts) handles each job kind,
    including those whose module the API imports only on use (the prevention planner)."""
    import subprocess

    code = (
        "from vera_api import investigation, plugins, worker; plugins.load_features(); "
        "print(' '.join(sorted(worker.HANDLERS)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.split()
    for kind in (
        "specialist_runner",
        "prevention_planner",
        "dispute_packet_preparer",
        "decision_packet_preparer",
        "response_reviewer",
        "follow_up_drafter",
        "live_verification",
        "dispute_outcome_ingest",
    ):
        assert kind in out, kind
