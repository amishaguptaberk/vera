"""Scenario replay harness.

A scenario is JSON data under evals/scenarios/NN_name.json: ordered steps and assertions on
persisted state. A step {"fragment": "name"} inlines the steps of evals/fragments/name.json (shared
journeys, e.g. up to the sent follow-up). A get step may "capture" response values by dotted path
into variables that later payloads and paths use as "${name}". Everything runs in REPLAY: no
provider key and no network (LIVE failure scenarios use an in-process stub transport). Commands
are posted with the key the case view advertises on the action; the runner never builds
idempotency keys itself.

    uv run python -m evals.harness [--suite all|cases|scenarios] [--only ID]

Two suites share this engine:
- scenarios (evals/scenarios): focused regression scenarios, one invariant each;
- cases (tests/fixtures/eval_cases, see evals/cases.py): the evaluation suite. Each case carries
  a full contract (facts, evidence, policy, workflow state, allowed and forbidden commands, audit
  events, final outcome) that deterministic evaluators check, plus global invariants. The run
  writes artifacts/eval-report.json and artifacts/eval-report.md.

The harness RESETS the database it points at (VERA_EVAL_DATABASE_URL, else
VERA_TEST_DATABASE_URL, else the local vera_test database). All data is synthetic.
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
FRAGMENTS = ROOT / "fragments"
RECORDINGS = ROOT / "recordings"
CASE = "CHG-1042"
# The in-process worker's clock: far after the demo clock, so every queued job is due.
WORKER_EPOCH = datetime(2031, 1, 1, tzinfo=UTC)
SPECS = ("charge_investigator", "related_transaction_investigator", "receipt_document_reviewer")
DEFAULT_DB = "postgresql+psycopg://vera:vera@127.0.0.1:54329/vera_test"


# A TestClient response. Starlette's TestClient may ship its own httpx build, so the type is
# not httpx.Response for mypy even though the interface is the same.
HttpResponse = Any


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
        cfg = Config(str(ROOT.parent / "alembic.ini"))
        # alembic.ini's script_location is relative: resolve it so any working directory works.
        cfg.set_main_option("script_location", str(ROOT.parent / "infra" / "migrations"))
        command.upgrade(cfg, "head")
        self.engine = create_engine(self.url)
        self.factory = sessionmaker(self.engine, expire_on_commit=False)
        app = create_app(Settings(database_url=self.url, env="synthetic"))
        self.client = TestClient(app)
        self.client.__enter__()
        self._saved: dict[tuple[str, str], Any] = {}
        self._env: dict[str, str | None] = {}
        self._tmp: list[Path] = []
        self.snapshots: dict[str, Any] = {}
        self.vars: dict[str, Any] = {}
        self.baseline_event = 0
        self.version_pin = "v?"
        # What a case did, in order: one entry per command, probe, route post and webhook.
        self.trace: list[dict[str, Any]] = []
        self.probes: list[dict[str, Any]] = []

    def close(self) -> None:
        self.restore()
        self.client.__exit__(None, None, None)
        self.engine.dispose()

    # seams (test-only module attributes; product code never switches them)
    def patch(self, name: str, value: Any, module: str = "investigation") -> None:
        import importlib

        mod = importlib.import_module(f"vera_api.{module}")
        self._saved.setdefault((module, name), getattr(mod, name))
        setattr(mod, name, value)

    def setenv(self, name: str, value: str) -> None:
        self._env.setdefault(name, os.environ.get(name))
        os.environ[name] = value

    def restore(self) -> None:
        import importlib

        for (module, name), value in self._saved.items():
            setattr(importlib.import_module(f"vera_api.{module}"), name, value)
        self._saved.clear()
        for name, old in self._env.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
        if self._env:
            from vera_api import voice

            voice.reset_provider()
        self._env.clear()
        os.environ["VERA_EXECUTION_MODE"] = "replay"
        os.environ.pop("NVIDIA_API_KEY", None)
        from vera_api import callbacks

        callbacks.TELEPHONY.next_outcome = "confirmed"
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
        self.vars.clear()
        self.trace = []
        self.probes = []

    def q(self, sql: str, **params: Any) -> list[Any]:
        from sqlalchemy import text

        with self.factory() as s:
            return list(s.execute(text(sql), params).all())

    def drain(self, start_minutes: int = 0, worker_id: str = "w-eval") -> int:
        from vera_api.worker import run_once

        t = WORKER_EPOCH + timedelta(minutes=start_minutes)
        n = 0
        with self.factory() as s:
            while run_once(s, worker_id=worker_id, now=t + timedelta(minutes=n)) is not None:
                n += 1
                if n > 20:
                    raise ScenarioFailure("worker did not go idle after 20 jobs")
        return n

    def stall_job(self) -> int:
        """A worker claims the next job and dies without finishing it (lock left behind)."""
        from vera_api.worker import claim_next

        with self.factory() as s:
            job = claim_next(s, "w-dead", WORKER_EPOCH)
            if job is None:
                raise ScenarioFailure("stall_job: no runnable job to claim")
            return int(job.id)

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


def _override_root(world: World, specialist: str, turns: list[dict[str, Any]]) -> Path:
    """A copy of the reference recordings with one specialist's CHG-1042 turns replaced.

    Used where a case needs the model to say something the single reference recording does not
    (e.g. the call agent reporting a voicemail). The step still runs in REPLAY through the same
    loop and validators; the turn is labelled provenance "eval-scripted" so it is never mistaken
    for a reference recording."""
    tmp = Path(tempfile.mkdtemp(prefix="vera-eval-"))
    world._tmp.append(tmp)
    root = tmp / "rec"
    shutil.copytree(RECORDINGS, root)
    folder = root / specialist / "v1"
    for old in folder.glob(f"{CASE}*.json"):
        old.unlink()
    for i, turn in enumerate(turns):
        name = f"{CASE}.json" if i == 0 else f"{CASE}.{i}.json"
        doc = {
            "content": turn.get("content", {}),
            "tool_calls": turn.get("tool_calls", []),
            "model_id": "eval-scripted",
            "provenance": "eval-scripted",
            "usage": {},
        }
        (folder / name).write_text(json.dumps(doc))
    return root


# ---- ElevenLabs voice provider over a mock transport (signed webhooks, no network) ----------

VOICE_SECRET = "whsec-eval-not-real"


def _elevenlabs(w: World) -> None:
    from vera_api import voice

    placed: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        placed.append(1)  # each placed call gets its own conversation: conv_eval_1, conv_eval_2
        n = len(placed)
        return httpx.Response(
            200,
            json={
                "success": True,
                "message": "ok",
                "conversation_id": f"conv_eval_{n}",
                "callSid": f"CA-eval-{n}",
            },
        )

    for name, value in {
        "VERA_VOICE_PROVIDER": "elevenlabs",
        "ELEVENLABS_API_KEY": "xi-eval-key-not-real",
        "ELEVENLABS_AGENT_ID": "agent_eval",
        "ELEVENLABS_AGENT_PHONE_NUMBER_ID": "phnum_eval",
        "ELEVENLABS_WEBHOOK_SECRET": VOICE_SECRET,
    }.items():
        w.setenv(name, value)
    w.patch("LIVE_TRANSPORT", httpx.MockTransport(handle), module="voice")
    voice.reset_provider()


def _post_webhook(w: World, doc: dict[str, Any], secret: str | None) -> HttpResponse:
    import time

    from vera_api import voice

    body = json.dumps(doc).encode()
    sig = voice.sign(secret or VOICE_SECRET, body, int(time.time()))
    return w.client.post(
        "/api/webhooks/voice/elevenlabs", content=body, headers={"ElevenLabs-Signature": sig}
    )


# ---- steps ------------------------------------------------------------------------------------


def expand(steps: list[dict[str, Any]], seen: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Inline {"fragment": name} steps (recursively) from evals/fragments/name.json."""
    out: list[dict[str, Any]] = []
    for step in steps:
        name = step.get("fragment")
        if name is None:
            out.append(step)
            continue
        if name in seen:
            raise ScenarioFailure(f"fragment {name} includes itself")
        path = FRAGMENTS / f"{name}.json"
        if not path.exists():
            raise ScenarioFailure(f"unknown fragment {name}")
        out.extend(expand(json.loads(path.read_text())["steps"], (*seen, name)))
    return out


def _subst(w: World, value: Any) -> Any:
    """Replace "${name}" with a captured variable (whole-string values keep their type)."""
    if isinstance(value, str):
        for name, got in w.vars.items():
            if value == "${" + name + "}":
                return got
            value = value.replace("${" + name + "}", str(got))
        return value
    if isinstance(value, list):
        return [_subst(w, v) for v in value]
    if isinstance(value, dict):
        return {k: _subst(w, v) for k, v in value.items()}
    return value


def _path(body: Any, path: str) -> Any:
    cur = body
    for part in path.split("."):
        cur = cur[int(part)] if isinstance(cur, list) else cur[part]
    return cur


def _find_action(view: dict[str, Any], command: str) -> dict[str, Any] | None:
    for a in [*view["available_actions"], *view.get("recovery_actions", [])]:
        if a["command"] == command:
            return dict(a)
    return None


def _check_http(step: dict[str, Any], resp: HttpResponse, ctx: str) -> None:
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
    """Post a command with the key and payload_defaults the case view advertises.

    Options: "payload" (merged over payload_defaults), "times" (repeat the identical request),
    "expect"/"expect_each", "capture" ({var: dotted path in the response}), "raw_key",
    "version_offset", and "route" for commands served on their own path (e.g. submit_otp at
    /api/verifications/${vid}/submit_otp), whose fields sit at the top level of the body."""
    w.switch(step["as"])
    case_id = step.get("case", CASE)
    view = w.view(case_id)
    command = step["command"]
    action = _find_action(view, command)
    offered = action is not None
    if action is None:
        # not offered to this role/state: post anyway (with "raw_key" when the case replays a
        # key it captured) so the gateway's answer is what gets asserted
        action = {"idempotency_key": "eval-probe:" + command, "payload_defaults": {}}
    key = _subst(w, step.get("raw_key")) or action["idempotency_key"]
    expected = view["case_version"] + int(step.get("version_offset", 0))
    payload = {**action.get("payload_defaults", {}), **_subst(w, step.get("payload", {}))}
    if "route" in step:
        path = _subst(w, step["route"])
        body = {"idempotency_key": key, "expected_case_version": expected, **payload}
        body.pop("verification_id", None)  # carried by the path
    else:
        path = f"/api/cases/{case_id}/commands/{command}"
        body = {"idempotency_key": key, "expected_case_version": expected, "payload": payload}
    for i in range(int(step.get("times", 1))):
        resp = w.client.post(path, json=body)
        w.trace.append(_trace_entry(step["as"], command, resp, offered=offered))
        exp = step.get("expect_each", [step.get("expect", {})])[
            min(i, len(step.get("expect_each", [0])) - 1)
        ]
        _check_http({"expect": exp}, resp, f"{ctx} attempt {i + 1}")
        if "capture" in step and resp.status_code == 200:
            for name, where in step["capture"].items():
                w.vars[name] = key if where == "$key" else _path(resp.json(), where)


def _trace_entry(
    role: str, command: str, resp: HttpResponse, *, offered: bool | None = None
) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    entry: dict[str, Any] = {"as": role, "command": command, "http": resp.status_code}
    if isinstance(body, dict):
        if body.get("code"):
            entry["code"] = body["code"]
        if body.get("status") in ("recorded", "replayed"):
            entry["result"] = body["status"]
    if offered is not None:
        entry["offered"] = offered
    return entry


def do_probe(w: World, probe: dict[str, Any], ctx: str, where: str = "step") -> dict[str, Any]:
    """Try a command that must NOT run here. It must not be offered as enabled to that role,
    the gateway must refuse it, and nothing may be written (row counts and case version are
    compared before and after). A refusal that only comes from the key check or the payload
    schema does not count: the probe must be stopped by a real gate unless the case says so."""
    role, command = probe["as"], probe["command"]
    case_id = probe.get("case", CASE)
    w.switch(role)
    view = w.view(case_id)
    action = _find_action(view, command)
    before = w.counts()
    key = action["idempotency_key"] if action else "eval-probe:" + command
    payload = {**(action or {}).get("payload_defaults", {}), **_subst(w, probe.get("payload", {}))}
    if "route" in probe:
        path = _subst(w, probe["route"])
        body: dict[str, Any] = {
            "idempotency_key": key,
            "expected_case_version": view["case_version"],
            **payload,
        }
        body.pop("verification_id", None)
    else:
        path = f"/api/cases/{case_id}/commands/{command}"
        body = {
            "idempotency_key": key,
            "expected_case_version": view["case_version"],
            "payload": payload,
        }
    resp = w.client.post(path, json=body)
    after = w.counts()
    try:
        code = resp.json().get("code")
    except ValueError:
        code = None
    weak = {"idempotency_key_mismatch", "schema_invalid"} - set(probe.get("allow_codes", []))
    want = probe.get("expect_code")
    problems = []
    if action is not None and not probe.get("may_be_offered"):
        # "may_be_offered": the action is legitimately on screen for other payloads (e.g.
        # record_decision for clear/unresolved) and only this payload must be refused
        problems.append("offered as an enabled action")
    if resp.status_code < 400:
        problems.append(f"accepted (HTTP {resp.status_code})")
    if after != before:
        problems.append("wrote rows")
    if want is not None and code != want:
        problems.append(f"refused with {code!r}, expected {want!r}")
    elif want is None and code in weak:
        problems.append(f"only stopped by {code!r}, not by a gate")
    result = {
        "as": role,
        "command": command,
        "where": where,
        "http": resp.status_code,
        "code": code,
        "expect_code": want,
        "gate": probe.get("gate") or GATE_OF_CODE.get(code or "", "other"),
        "passed": not problems,
        "problems": problems,
    }
    w.probes.append(result)
    w.trace.append(
        {"as": role, "command": command, "http": resp.status_code, "code": code, "probe": True}
    )
    if problems and where == "step" and not probe.get("soft"):
        raise ScenarioFailure(f"{ctx}: forbidden {command} as {role}: {'; '.join(problems)}")
    return result


# Which gate a refusal code belongs to (report grouping; the gateway decides, not this table).
GATE_OF_CODE = {
    "role_forbidden": "permission",
    "policy_blocked": "policy",
    "approval_required": "approval",
    "approval_stale": "stale_approval",
    "invalid_step": "state",
    "case_closed": "state",
    "stale_case_version": "concurrency",
    "idempotency_key_conflict": "idempotency",
    "attachment_type_rejected": "validation",
    "schema_invalid": "validation",
    # record guards: the feature's own records refuse the command (gateway stage 8b)
    "related_charge_reviewed": "record_guard",
    "verification_not_active": "record_guard",
    "closure_incomplete": "record_guard",
}


def do_service(w: World, step: dict[str, Any], ctx: str) -> None:
    from sqlalchemy import text

    name = step["service"]
    if name == "drain_worker":
        ran = w.drain(int(step.get("start_minutes", 0)))
        if "expect_jobs" in step and ran != step["expect_jobs"]:
            raise ScenarioFailure(f"{ctx}: worker ran {ran} job(s), expected {step['expect_jobs']}")
    elif name == "stall_job":
        w.vars["stalled_job"] = w.stall_job()
    elif name == "recording_override":
        w.patch("RECORDINGS_ROOT", _override_root(w, step["specialist"], step["turns"]))
    elif name == "voice_provider":
        _elevenlabs(w)
    elif name == "webhook":
        resp = _post_webhook(w, _subst(w, step["doc"]), step.get("secret"))
        w.trace.append(
            {
                "as": "provider",
                "command": f"webhook:{step['doc']['type']}",
                "http": resp.status_code,
                "result": resp.json().get("result"),
            }
        )
        _check_http(step, resp, ctx)
        if "expect_result" in step and resp.json().get("result") != step["expect_result"]:
            raise ScenarioFailure(
                f"{ctx}: webhook result {resp.json().get('result')!r}, "
                f"expected {step['expect_result']!r}"
            )
    elif name == "reset":
        w.reset()
    elif name == "demo":
        resp = w.client.post(_subst(w, f"/api/demo/{step['demo']}"), json=step.get("body", {}))
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
    elif name == "sql_must_fail":  # a direct write the database itself must refuse
        # Non-vacuous: the rows the write targets must exist, or "refused" proves nothing.
        if "rows_exist" in step and not w.q(step["rows_exist"])[0][0]:
            raise ScenarioFailure(f"{ctx}: precondition found no rows: {step['rows_exist']}")
        with w.engine.connect() as conn:
            tx = conn.begin()
            try:
                conn.execute(text(step["query"]))
            except Exception as exc:  # refused: the expected outcome
                refused = str(exc).splitlines()[0][:160]
                w.trace.append(
                    {
                        "as": "database",
                        "command": "sql",
                        "http": 0,
                        "code": "refused",
                        "detail": refused,
                    }
                )
            else:
                raise ScenarioFailure(f"{ctx}: the database accepted {step['query']!r}")
            finally:
                tx.rollback()
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


def _check_body(w: World, step: dict[str, Any], resp: Any, ctx: str) -> None:
    for path, want in step.get("json", {}).items():
        cur = _path(resp.json(), path)
        if cur != want:
            raise ScenarioFailure(f"{ctx}: {path} is {cur!r}, expected {want!r}")
    for path, words in step.get("json_excludes", {}).items():
        text = json.dumps(_path(resp.json(), path) if path != "." else resp.json()).lower()
        for word in words:
            if word.lower() in text:
                raise ScenarioFailure(f"{ctx}: {path} must not contain {word!r}")
    for name, path in step.get("capture", {}).items():
        w.vars[name] = _path(resp.json(), path)


def do_get(w: World, step: dict[str, Any], ctx: str) -> None:
    if "as" in step:
        w.switch(step["as"])
    resp = w.client.get(_subst(w, step["get"]))
    _check_http(step, resp, ctx)
    _check_body(w, step, resp, ctx)


def do_post(w: World, step: dict[str, Any], ctx: str) -> None:
    """A non-command route (e.g. the cardholder's reply or the synthetic OTP outbox)."""
    if "as" in step:
        w.switch(step["as"])
    resp = w.client.post(_subst(w, step["post"]), json=_subst(w, step.get("body", {})))
    route = step["post"].split("${")[0].rstrip("/")
    w.trace.append(_trace_entry(step.get("as", "-"), f"POST {route}", resp))
    _check_http(step, resp, ctx)
    _check_body(w, step, resp, ctx)


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
    steps = expand(steps)
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
            elif "post" in step:
                do_post(w, step, ctx)
            elif "probe" in step:
                for probe in step["probe"] if isinstance(step["probe"], list) else [step["probe"]]:
                    do_probe(w, probe, ctx)
            if "assert" in step:
                check(w, step["assert"], ctx)
        except ScenarioFailure:
            raise
        except Exception as exc:  # surface as a failed invariant with context
            raise ScenarioFailure(f"{ctx}: {type(exc).__name__}: {exc}") from exc


def _label(step: dict[str, Any]) -> str:
    if "probe" in step:
        probes = step["probe"] if isinstance(step["probe"], list) else [step["probe"]]
        return "probe " + ",".join(p["command"] for p in probes)
    return str(step.get("command") or step.get("service") or step.get("get") or step.get("post"))


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
    from evals import cases as case_suite

    ap = argparse.ArgumentParser(prog="python -m evals.harness")
    ap.add_argument("--suite", choices=("all", "cases", "scenarios"), default="all")
    ap.add_argument("--only", help="scenario number/prefix (e.g. 05) or case id (e.g. EC-07)")
    ap.add_argument("--report-dir", default=str(ROOT.parent / "artifacts"))
    ap.add_argument("--no-report", action="store_true", help="do not write the report files")
    ap.add_argument(
        "--judge",
        action="store_true",
        help="also run the optional LLM judge (needs NVIDIA_API_KEY; qualitative)",
    )
    args = ap.parse_args(argv)
    scen: list[Result] = []
    found: list[case_suite.CaseResult] = []
    write_report = args.suite == "all" and not args.only and not args.no_report
    sens: dict[str, Any] | None = None
    perms: dict[str, Any] | None = None
    with world() as w:
        if args.suite in ("all", "scenarios"):
            for path, sc in load_scenarios(args.only):
                scen.append(run_scenario(w, path, sc))
        if args.suite in ("all", "cases"):
            for path, case in case_suite.load_cases(args.only):
                found.append(case_suite.run_case(w, path, case))
        if write_report:
            from evals import permissions, sensitivity

            sens = sensitivity.run(w)
            perms = permissions.run(w)
    if scen:
        width = max(len(r.scenario) for r in scen)
        out(f"{'SCENARIO'.ljust(width)}  RESULT   DETAIL")
        for r in scen:
            out(f"{r.scenario.ljust(width)}  {r.status.ljust(7)}  {r.detail or r.title}")
        n = {s: sum(1 for r in scen if r.status == s) for s in ("PASS", "FAIL", "SKIPPED")}
        out(f"\n{n['PASS']} passed, {n['FAIL']} failed, {n['SKIPPED']} skipped (pending)\n")
    if found:
        out(f"{'CASE'.ljust(6)}  RESULT  CHECKS  TITLE / FIRST FAILURE")
        for c in found:
            out(
                f"{c.case_id.ljust(6)}  {c.status.ljust(6)}  {len(c.checks):>6}  "
                f"{c.first_failure or c.title}"
            )
        ok = sum(c.status == "PASS" for c in found)
        out(f"\n{ok} of {len(found)} evaluation cases passed")
    if write_report:
        from evals import baseline, judge, report

        rep = report.build(
            found, scen, baseline.run(), judge.run() if args.judge else None, sens, perms
        )
        j, m = report.write(rep, Path(args.report_dir))
        c = rep["counters"]
        out(f"report: {j} and {m}")
        out("counters: " + ", ".join(f"{k}={v}" for k, v in c.items()))
        if sens is not None:
            out(f"sensitivity: {sens['detected']} of {sens['total']} injected defects detected")
        if perms is not None:
            out(
                f"permission matrix: {perms['refused']} of {perms['pairs']} (command, role) pairs "
                f"refused across {perms['commands']} commands"
            )
        if rep["summary"]["required_behaviours_uncovered"]:
            out(f"uncovered: {rep['summary']['required_behaviours_uncovered']}")
            return 1
        if sens is not None and sens["detected"] != sens["total"]:
            return 1
        if perms is not None and perms["failures"]:
            return 1
    failed = any(r.status == "FAIL" for r in scen) or any(c.status == "FAIL" for c in found)
    return 1 if failed or not (scen or found) else 0


if __name__ == "__main__":
    sys.exit(main())
