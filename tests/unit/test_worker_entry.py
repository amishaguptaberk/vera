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
