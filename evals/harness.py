"""Scenario replay harness (VER-013).

A scenario is JSON data under evals/scenarios/NN_name.json: ordered steps and assertions on
persisted state. Everything runs in REPLAY: no provider key and no network (LIVE failure
scenarios use an in-process stub transport). Commands are posted with the key the case view
advertises on the action; the runner never builds idempotency keys itself.

    uv run python -m evals.harness [--only NN]

The harness RESETS the database it points at (VERA_EVAL_DATABASE_URL, else
VERA_TEST_DATABASE_URL, else the local vera_test database).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent
SCENARIOS = ROOT / "scenarios"
RECORDINGS = ROOT / "recordings"
CASE = "CHG-1042"
SPECS = ("charge_investigator", "related_transaction_investigator", "receipt_document_reviewer")
DEFAULT_DB = "postgresql+psycopg://vera:vera@127.0.0.1:54329/vera_test"


class ScenarioFailure(AssertionError):
    """A broken invariant, naming case, workflow version, step and the invariant."""


@dataclass
class Result:
    scenario: str
    status: str  # PASS | FAIL | SKIPPED
    detail: str = ""
    title: str = ""


def db_url() -> str:
    return (
        os.environ.get("VERA_EVAL_DATABASE_URL")
        or os.environ.get("VERA_TEST_DATABASE_URL")
        or DEFAULT_DB
    )


def load_scenarios(only: str | None = None) -> list[tuple[Path, dict[str, Any]]]:
    out = []
    for path in sorted(SCENARIOS.glob("*.json")):
        if only and not path.name.startswith(only.zfill(2) if only.isdigit() else only):
            continue
        out.append((path, json.loads(path.read_text())))
    return out


# ---- the world a scenario runs in ----------------------------------------------------------


class World:
    """App + DB + worker + test seams for one process; reset between scenarios."""

    def __init__(self) -> None:
        from alembic import command
        from alembic.config import Config
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from vera_api.app import create_app
        from vera_api.config import Settings

        self.url = db_url()
        os.environ["VERA_DATABASE_URL"] = self.url
        os.environ["VERA_EXECUTION_MODE"] = "replay"
        os.environ.pop("NVIDIA_API_KEY", None)
        command.upgrade(Config(str(ROOT.parent / "alembic.ini")), "head")
        self.engine = create_engine(self.url)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        app = create_app(Settings(database_url=self.url, env="synthetic"))
        self.client = TestClient(app)
        self.client.__enter__()
        self._saved: dict[str, Any] = {}
        self._tmp: list[Path] = []
        self.snapshots: dict[str, Any] = {}
        self.baseline_event = 0
        self.version_pin = "v?"

    def close(self) -> None:
        self.restore()
        self.client.__exit__(None, None, None)
        self.engine.dispose()

    # seams
    def patch(self, name: str, value: Any) -> None:
        from vera_api import investigation

        self._saved.setdefault(name, getattr(investigation, name))
        setattr(investigation, name, value)

    def restore(self) -> None:
        from vera_api import investigation

        for name, value in self._saved.items():
            setattr(investigation, name, value)
        self._saved.clear()
        os.environ["VERA_EXECUTION_MODE"] = "replay"
        os.environ.pop("NVIDIA_API_KEY", None)
        for p in self._tmp:
            shutil.rmtree(p, ignore_errors=True)
        self._tmp.clear()

    def reset(self) -> None:
        from sqlalchemy import text

        self.restore()
        self.patch("RECORDINGS_ROOT", RECORDINGS)
        self.patch("LIVE_SLEEP", lambda _s: None)
        with self.factory() as s:
            s.execute(text("truncate table jobs, workflow_runs cascade"))
            for t in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                s.execute(text(f"delete from {t}"))
            s.commit()
        self.client.cookies.clear()
        r = self.client.post("/api/demo/reset")
        assert r.status_code == 200, r.text
        self.baseline_event = int(self.q("select coalesce(max(id),0) from audit_events")[0][0])
        self.snapshots.clear()

    def q(self, sql: str, **params: Any) -> list[Any]:
        from sqlalchemy import text

        with self.factory() as s:
            return list(s.execute(text(sql), params).all())

    def drain(self) -> int:
        from vera_api.worker import run_once

        t = datetime(2031, 1, 1, tzinfo=UTC)
        n = 0
        with self.factory() as s:
            while run_once(s, worker_id="w-eval", now=t + timedelta(minutes=n)) is not None:
                n += 1
                if n > 20:
                    raise ScenarioFailure("worker did not go idle after 20 jobs")
        return n

    def view(self, case_id: str = CASE) -> dict[str, Any]:
        r = self.client.get(f"/api/cases/{case_id}")
        assert r.status_code == 200, r.text
        return dict(r.json())

    def switch(self, role: str) -> None:
        r = self.client.post("/api/session/role", json={"role": role})
        if r.status_code != 200:
            raise ScenarioFailure(f"cannot switch to role {role}: {r.status_code} {r.text}")

    def counts(self) -> dict[str, Any]:
        tables = ("audit_events", "state_transitions", "idempotency_keys", "findings", "claims")
        out: dict[str, Any] = {t: self.q(f"select count(*) from {t}")[0][0] for t in tables}
        out["cases"] = [
            tuple(r) for r in self.q("select id, case_version, state, step from cases order by id")
        ]
        return out


# ---- LIVE stub (in-process transport) -------------------------------------------------------


def _live_stub() -> httpx.MockTransport:
    turns = {
        n: [
            json.loads((RECORDINGS / n / "v1" / f).read_text())
            for f in (f"{CASE}.json", f"{CASE}.1.json")
        ]
        for n in SPECS
    }

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        name = next(n for n in SPECS if n.split("_")[0].capitalize() in system.split(".")[0])
        has_tool = any(m["role"] == "tool" for m in body["messages"])
        turn = turns[name][1 if has_tool else 0]
        if turn["tool_calls"]:
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                    }
                    for tc in turn["tool_calls"]
                ],
            }
        else:
            msg = {"role": "assistant", "content": json.dumps(turn["content"])}
        return httpx.Response(200, json={"model": "stub/live", "choices": [{"message": msg}]})

    return httpx.MockTransport(handle)


# ---- recordings variants ---------------------------------------------------------------------


def _variant_root(world: World, variant: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="vera-eval-"))
    world._tmp.append(tmp)
    root = tmp / "rec"
    if variant == "empty":
        return root
    shutil.copytree(RECORDINGS, root)
    if variant == "ungrounded":
        final = json.loads((RECORDINGS / "charge_investigator/v1/CHG-1042.1.json").read_text())
        final["content"]["findings"][0]["citations"][0]["value"] = 248000
        for n in (1, 2, 3):
            (root / "charge_investigator/v1" / f"CHG-1042.{n}.json").write_text(json.dumps(final))
    elif variant == "scope_violation":
        path = root / "charge_investigator/v1/CHG-1042.json"
        turn = json.loads(path.read_text())
        turn["tool_calls"].append(
            {
                "id": "x",
                "name": "read_field",
                "arguments": {"record_id": "PRF-4418", "field": "phone"},
            }
        )
        path.write_text(json.dumps(turn))
    elif variant == "two_missing":
        shutil.rmtree(root / "charge_investigator")
        shutil.rmtree(root / "related_transaction_investigator")
    else:
        raise ScenarioFailure(f"unknown recordings variant {variant}")
    return root


# ---- steps ------------------------------------------------------------------------------------


def _find_action(view: dict[str, Any], command: str) -> dict[str, Any] | None:
    for a in [*view["available_actions"], *view.get("recovery_actions", [])]:
        if a["command"] == command:
            return dict(a)
    return None


def _check_http(step: dict[str, Any], resp: httpx.Response, ctx: str) -> None:
    exp = step.get("expect", {})
    want = exp.get("http", 200)
    if resp.status_code != want:
        raise ScenarioFailure(f"{ctx}: HTTP {resp.status_code}, expected {want}: {resp.text[:300]}")
    try:
        body = resp.json()
    except ValueError:
        body = {}
    for k in ("code", "blocked_reason"):
        if k in exp and body.get(k) != exp[k]:
            raise ScenarioFailure(f"{ctx}: {k} {body.get(k)!r}, expected {exp[k]!r}")
    if "result_status" in exp and body.get("status") != exp["result_status"]:
        raise ScenarioFailure(
            f"{ctx}: result status {body.get('status')!r}, expected {exp['result_status']!r}"
        )


def do_command(w: World, step: dict[str, Any], ctx: str) -> None:
    w.switch(step["as"])
    case_id = step.get("case", CASE)
    view = w.view(case_id)
    command = step["command"]
    action = _find_action(view, command)
    if action is None and step.get("raw_key") is None:
        # not offered to this role/state: probe the gateway anyway so rejection is asserted
        action = {"idempotency_key": "eval-probe:" + command, "payload_defaults": {}}
    assert action is not None
    key = step.get("raw_key") or action["idempotency_key"]
    expected = view["case_version"] + int(step.get("version_offset", 0))
    body = {
        "idempotency_key": key,
        "expected_case_version": expected,
        "payload": {**action.get("payload_defaults", {}), **step.get("payload", {})},
    }
    for i in range(int(step.get("times", 1))):
        resp = w.client.post(f"/api/cases/{case_id}/commands/{command}", json=body)
        exp = step.get("expect_each", [step.get("expect", {})])[
            min(i, len(step.get("expect_each", [0])) - 1)
        ]
        _check_http({"expect": exp}, resp, f"{ctx} attempt {i + 1}")


def do_service(w: World, step: dict[str, Any], ctx: str) -> None:
    from sqlalchemy import text

    name = step["service"]
    if name == "drain_worker":
        w.drain()
    elif name == "reset":
        w.reset()
    elif name == "demo":
        resp = w.client.post(f"/api/demo/{step['demo']}", json=step.get("body", {}))
        _check_http(step, resp, ctx)
    elif name == "recordings":
        w.patch("RECORDINGS_ROOT", _variant_root(w, step["variant"]))
    elif name == "live":
        os.environ["VERA_EXECUTION_MODE"] = "live"
        os.environ["NVIDIA_API_KEY"] = "eval-key-not-real"
        w.patch("RECORDINGS_ROOT", _variant_root(w, "empty"))
        if step["transport"] == "fail500":
            w.patch("LIVE_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(500)))
        else:
            w.patch("LIVE_TRANSPORT", _live_stub())
    elif name == "replay_recordings":
        w.patch("RECORDINGS_ROOT", RECORDINGS)
    elif name == "crash_once":
        crashed: list[str] = []

        def hook(key: str) -> None:
            if key == step["at"] and not crashed:
                crashed.append(key)
                raise RuntimeError("worker killed (eval)")

        w.patch("NODE_HOOK", hook)
    elif name == "snapshot":
        w.snapshots[step["name"]] = w.counts()
    elif name == "record_finding":
        from vera_api.auth import Actor
        from vera_api.gateway import execute_command
        from vera_domain.clock import default_demo_clock
        from vera_domain.enums import Role
        from vera_domain.evidence import SERVICE_REGISTRY

        payload = step["payload"]
        from vera_domain.errors import CommandError

        with w.factory() as s:
            version = s.execute(
                text("select case_version from cases where id=:c"), {"c": CASE}
            ).scalar()
            s.rollback()
            try:
                execute_command(
                    s,
                    now=default_demo_clock().now(),
                    case_id=CASE,
                    command="record_finding",
                    key=SERVICE_REGISTRY["record_finding"].key_template.format(**payload),
                    expected_version=int(version or 0),
                    payload=payload,
                    actor=Actor(
                        "svc-specialist", "svc", Role.SPECIALIST, frozenset({Role.SPECIALIST})
                    ),
                    request_id="eval",
                )
            except CommandError as err:
                want = step.get("expect_error")
                if want is None or err.code != want:
                    raise
            else:
                if step.get("expect_error"):
                    raise ScenarioFailure(
                        f"{ctx}: expected rejection {step['expect_error']}, finding was recorded"
                    )
    elif name == "sql":  # test-data setup only (e.g. force a closed case); never an assertion
        with w.factory() as s:
            s.execute(text(step["query"]))
            s.commit()
    elif name == "two_cookies":
        good = w.client.cookies.get("vera_session")
        assert good is not None
        body, _, mac = good.rpartition(".")
        header = f"vera_session={body}.{'0' * len(mac)}; vera_session={good}"
        w.client.cookies.clear()
        resp = w.client.get("/api/session", headers={"Cookie": header})
        _check_http(step, resp, ctx)
        got = resp.json()
        if got["user"]["id"] != "usr-sam-rivera" or got["active_role"] != "analyst":
            raise ScenarioFailure(f"{ctx}: two session cookies must resolve to no session")
    else:
        raise ScenarioFailure(f"unknown service step {name}")


def do_get(w: World, step: dict[str, Any], ctx: str) -> None:
    if "as" in step:
        w.switch(step["as"])
    resp = w.client.get(step["get"])
    _check_http(step, resp, ctx)
    for path, want in step.get("json", {}).items():
        cur: Any = resp.json()
        for part in path.split("."):
            cur = cur[int(part)] if isinstance(cur, list) else cur[part]
        if cur != want:
            raise ScenarioFailure(f"{ctx}: {path} is {cur!r}, expected {want!r}")


# ---- assertions on persisted state ----------------------------------------------------------


def _eq(ctx: str, what: str, got: Any, want: Any) -> None:
    if got != want:
        raise ScenarioFailure(f"{ctx}: invariant '{what}' broken: got {got!r}, expected {want!r}")


def check(w: World, spec: dict[str, Any], ctx: str) -> None:
    view = w.view(spec.get("case", CASE))
    cid = spec.get("case", CASE)
    if "case" in spec and isinstance(spec["case"], dict):
        pass
    if "state" in spec:
        _eq(ctx, "state", view["state"], spec["state"])
    if "step" in spec:
        _eq(ctx, "step", view["step"], spec["step"])
    if "version" in spec:
        _eq(ctx, "case_version", view["case_version"], spec["version"])
    if "pins" in spec:
        for k, v in spec["pins"].items():
            _eq(ctx, f"pins.{k}", view["pins"][k], v)
    if "enabled_actions" in spec:
        _eq(
            ctx,
            "enabled actions",
            sorted(a["command"] for a in view["available_actions"]),
            sorted(spec["enabled_actions"]),
        )
    if "actions_include" in spec:
        have = {a["command"] for a in view["available_actions"]}
        _eq(ctx, "enabled actions include", sorted(set(spec["actions_include"]) - have), [])
    if "actions_exclude" in spec:
        have = {a["command"] for a in view["available_actions"]}
        _eq(ctx, "actions not enabled", sorted(set(spec["actions_exclude"]) & have), [])
    if "blocked_actions" in spec:
        blocked = {b["command"]: b["blocked_reason"] for b in view["blocked_actions"]}
        for name, reason in spec["blocked_actions"].items():
            if name not in blocked:
                raise ScenarioFailure(
                    f"{ctx}: invariant 'blocked action {name}' broken: not blocked"
                )
            if reason is not None and reason not in blocked[name]:
                raise ScenarioFailure(
                    f"{ctx}: blocked reason for {name} is {blocked[name]!r}, expected {reason!r}"
                )
    if "recovery_actions" in spec:
        _eq(
            ctx,
            "recovery actions",
            sorted(a["command"] for a in view["recovery_actions"]),
            sorted(spec["recovery_actions"]),
        )
    if "policy" in spec:
        pol = view["policy"] or {}
        for k, v in spec["policy"].items():
            _eq(ctx, f"policy.{k}", pol.get(k), v)
    if "evidence" in spec:
        reg = w.client.get(f"/api/cases/{cid}/evidence").json()
        ev = spec["evidence"]
        statuses = {r["record_id"]: r["status"] for r in reg["records"]}
        for rec, st in ev.get("records", {}).items():
            _eq(ctx, f"evidence status {rec}", statuses.get(rec), st)
        if "missing" in ev:
            _eq(ctx, "evidence missing", reg["missing"], ev["missing"])
        if "open_conflicts" in ev:
            _eq(ctx, "open conflicts", len(reg["open_conflicts"]), ev["open_conflicts"])
        checks = {c["key"]: c["status"] for c in reg["checks"]}
        for k, st in ev.get("checks", {}).items():
            _eq(ctx, f"evidence check {k}", checks.get(k), st)
        for rec, ver in ev.get("current_versions", {}).items():
            cur = {r["record_id"]: r["current_version"] for r in reg["records"]}
            _eq(ctx, f"current version {rec}", cur.get(rec), ver)
        if "snapshot_changed_since" in ev:
            prior = w.snapshots[ev["snapshot_changed_since"]]
            _eq(ctx, "snapshot hash changed", reg["snapshot_hash"] != prior, True)
        if "remember_snapshot" in ev:
            w.snapshots[ev["remember_snapshot"]] = reg["snapshot_hash"]
    if "findings" in spec:
        reg = w.client.get(f"/api/cases/{cid}/evidence").json()
        fs = reg["findings"]
        f = spec["findings"]
        if "count" in f:
            _eq(ctx, "findings count", len(fs), f["count"])
        if f.get("all_cited"):
            for x in fs:
                if not x["links"] or any(
                    not (lk["record_id"] and lk["version"] >= 1 and lk["field"])
                    for lk in x["links"]
                ):
                    raise ScenarioFailure(
                        f"{ctx}: invariant 'finding needs citations' broken: {x['finding_id']}"
                    )
        for want in f.get("expect", []):
            cites = {tuple(c) for c in want.get("cites", [])}
            ok = any(
                x["kind"] == want["kind"]
                and cites <= {(lk["record_id"], lk["field"]) for lk in x["links"]}
                and (want.get("status") is None or x["status"] == want["status"])
                for x in fs
            )
            if not ok:
                raise ScenarioFailure(f"{ctx}: invariant 'finding {want}' broken: none matches")
    if "claims" in spec:
        rows = w.q("select statement from claims where case_id=:c", c=cid)
        c = spec["claims"]
        if "count" in c:
            _eq(ctx, "claims count", len(rows), c["count"])
        for s in c.get("contain", []):
            _eq(ctx, f"claim '{s}' recorded", any(s in r[0] for r in rows), True)
    if "reports" in spec:
        rows = w.q("select statement from reports where case_id=:c", c=cid)
        for text_ in spec["reports"].get("contain", []):
            _eq(ctx, f"report '{text_}' stored", any(text_ in r[0] for r in rows), True)
        if "count" in spec["reports"]:
            _eq(ctx, "reports count", len(rows), spec["reports"]["count"])
    if "events" in spec:
        e = spec["events"]
        rows = w.q(
            "select type from audit_events where case_id=:c and id>:b order by id",
            c=cid,
            b=w.baseline_event,
        )
        types = [r[0] for r in rows]
        if e.get("mode", "exact") == "exact":
            _eq(ctx, "event sequence", types, e["types"])
        else:
            it = iter(types)
            ok = all(any(t == x for x in it) for t in e["types"])
            if not ok:
                raise ScenarioFailure(
                    f"{ctx}: invariant 'event subsequence' broken: wanted {e['types']} in {types}"
                )
        for t in e.get("absent", []):
            _eq(ctx, f"no {t} event", t in types, False)
    if "idempotency" in spec:
        for row in spec["idempotency"]:
            got = w.q("select attempts, status from idempotency_keys where key=:k", k=row["key"])
            if not got:
                raise ScenarioFailure(
                    f"{ctx}: invariant 'idempotency row {row['key']}' broken: missing"
                )
            if "attempts" in row:
                _eq(ctx, f"attempts for {row['key']}", got[0][0], row["attempts"])
            if "status" in row:
                _eq(ctx, f"status for {row['key']}", got[0][1], row["status"])
    if "approvals" in spec:
        have = w.q("select to_regclass('public.approvals')")[0][0]
        n = w.q("select count(*) from approvals")[0][0] if have else 0
        _eq(ctx, "approval count", n, spec["approvals"]["count"])
    if "adapter_calls" in spec:
        have = w.q("select to_regclass('public.adapter_calls')")[0][0]
        n = w.q("select count(*) from adapter_calls")[0][0] if have else 0
        _eq(ctx, "adapter call count", n, spec["adapter_calls"]["count"])
    if "runs" in spec:
        runs = w.client.get(f"/api/cases/{cid}/runs").json()
        r = spec["runs"]
        _eq(ctx, "run count", len(runs), r.get("count", len(runs)))
        if runs and "status" in r:
            _eq(ctx, "run status", runs[-1]["status"], r["status"])
        if runs and "mode" in r:
            _eq(ctx, "run mode", runs[-1]["mode"], r["mode"])
        if runs and "workflow_version" in r:
            _eq(ctx, "run workflow_version", runs[-1]["workflow_version"], r["workflow_version"])
        steps = {s["step_key"]: s for s in (runs[-1]["steps"] if runs else [])}
        for k, st in r.get("steps", {}).items():
            _eq(ctx, f"step {k} status", steps.get(k, {}).get("status"), st)
        for k, why in r.get("failure_reasons", {}).items():
            _eq(ctx, f"step {k} failure_reason", steps.get(k, {}).get("failure_reason"), why)
        for k, mode in r.get("execution_modes", {}).items():
            _eq(ctx, f"step {k} execution_mode", steps.get(k, {}).get("execution_mode"), mode)
    if "unchanged_since" in spec:
        _eq(ctx, "nothing written since snapshot", w.counts(), w.snapshots[spec["unchanged_since"]])
    for q in spec.get("sql", []):
        got = w.q(q["query"])
        _eq(ctx, q.get("name", q["query"]), [list(r) for r in got], q["equals"])


# ---- running ---------------------------------------------------------------------------------


def run_scenario(w: World, path: Path, sc: dict[str, Any]) -> Result:
    name = path.stem
    title = sc.get("title", name)
    if sc.get("status") == "pending":
        return Result(name, "SKIPPED", f"pending: requires {sc['requires']}", title)
    w.reset()
    try:
        play(w, name, sc["steps"], sc.get("case", CASE))
    except ScenarioFailure as exc:
        return Result(name, "FAIL", str(exc), title)
    finally:
        w.restore()
    return Result(name, "PASS", "", title)


def play(w: World, name: str, steps: list[dict[str, Any]], case: str = CASE) -> None:
    """Run steps in order against an already reset world; raises ScenarioFailure."""
    for i, step in enumerate(steps, 1):
        ver = w.view(case)["pins"]["workflow_version"]
        label = step.get("note", _label(step))
        ctx = f"[{name}] case={case} workflow=v{ver} step {i}/{len(steps)} ({label})"
        try:
            if "command" in step:
                do_command(w, step, ctx)
            elif "service" in step:
                do_service(w, step, ctx)
            elif "get" in step:
                do_get(w, step, ctx)
            if "assert" in step:
                check(w, step["assert"], ctx)
        except ScenarioFailure:
            raise
        except Exception as exc:  # surface as a failed invariant with context
            raise ScenarioFailure(f"{ctx}: {type(exc).__name__}: {exc}") from exc


def _label(step: dict[str, Any]) -> str:
    return str(step.get("command") or step.get("service") or step.get("get"))


@contextmanager
def world() -> Iterator[World]:
    w = World()
    try:
        yield w
    finally:
        w.close()


def run_all(only: str | None = None) -> list[Result]:
    results: list[Result] = []
    with world() as w:
        for path, sc in load_scenarios(only):
            results.append(run_scenario(w, path, sc))
    return results


def main(argv: list[str] | None = None, out: Callable[[str], Any] = print) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.harness")
    ap.add_argument("--only", help="scenario number or name prefix, e.g. 05")
    args = ap.parse_args(argv)
    results = run_all(args.only)
    width = max((len(r.scenario) for r in results), default=10)
    out(f"{'SCENARIO'.ljust(width)}  RESULT   DETAIL")
    for r in results:
        out(f"{r.scenario.ljust(width)}  {r.status.ljust(7)}  {r.detail or r.title}")
    n = {s: sum(1 for r in results if r.status == s) for s in ("PASS", "FAIL", "SKIPPED")}
    out(f"\n{n['PASS']} passed, {n['FAIL']} failed, {n['SKIPPED']} skipped (pending)")
    return 1 if n["FAIL"] or not results else 0


if __name__ == "__main__":
    sys.exit(main())
