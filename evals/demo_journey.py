"""Scripted end-to-end demo journey for CHG-1042 over HTTP, as the real demo roles.

    uv run python evals/demo_journey.py --base http://127.0.0.1:8300 [--no-reset] [--json]

Rules this script keeps (so it proves the product, not itself):
- It only talks HTTP to a running API (infra/demo.sh up). It never touches the database.
- It never builds idempotency keys: every command is posted with the `idempotency_key` and
  `payload_defaults` the case view advertises on the action (available_actions /
  recovery_actions). User-entered fields are merged over payload_defaults, as the UI does.
- Roles are switched with POST /api/session/role (demo-only route, synthetic environment).
- Investigation work is done by the real worker process; the script polls /runs.
- It runs every stage the server offers and STOPS HONESTLY at the first stage whose commands
  or routes are not offered, then prints a readiness table. Stage 16 (audit trail and
  exposure) always runs because it only reads.

Exit code 0 only if every stage that was reached passed its assertions.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

CASE = "CHG-1042"
SPECIALISTS = {
    "charge_investigator",
    "related_transaction_investigator",
    "receipt_document_reviewer",
}


class NotOffered(Exception):
    """The server does not offer this stage's command or route (feature not merged yet)."""


class StageFailed(AssertionError):
    """The stage was offered but an assertion on the server's answer failed."""


@dataclass
class Stage:
    num: int
    name: str
    status: str = "not reached"  # PASS | FAIL | NOT OFFERED | not reached
    evidence: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        self.evidence.append(text)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise StageFailed(msg)


class Vera:
    """Thin HTTP client: one cookie jar, one active demo role at a time."""

    def __init__(self, base: str, timeout: float = 30.0) -> None:
        self.http = httpx.Client(base_url=base.rstrip("/"), timeout=timeout)
        self.role = "analyst"
        self.posted: list[str] = []

    # --- reads -----------------------------------------------------------------------------
    def get(self, path: str, *, optional: bool = False) -> Any:
        r = self.http.get(path)
        if optional and r.status_code in (404, 405):
            raise NotOffered(f"GET {path} -> {r.status_code}")
        check(r.status_code == 200, f"GET {path} -> {r.status_code} {r.text[:300]}")
        return r.json()

    def view(self) -> dict[str, Any]:
        return dict(self.get(f"/api/cases/{CASE}"))

    def events(self) -> list[dict[str, Any]]:
        return list(self.get(f"/api/cases/{CASE}/activity")["events"])

    def event_types(self) -> list[str]:
        return [e["type"] for e in self.events()]

    def runs(self) -> list[dict[str, Any]]:
        return list(self.get(f"/api/cases/{CASE}/runs"))

    # --- writes ----------------------------------------------------------------------------
    def as_role(self, role: str) -> dict[str, Any]:
        r = self.http.post("/api/session/role", json={"role": role})
        check(r.status_code == 200, f"switch to {role}: {r.status_code} {r.text[:200]}")
        out = dict(r.json())
        check(out["active_role"] == role, f"active role is {out['active_role']}, wanted {role}")
        self.role = role
        return out

    def find(self, names: Iterable[str], view: dict[str, Any] | None = None) -> dict[str, Any]:
        """First ENABLED offered action whose command is in `names` (in preference order)."""
        view = view or self.view()
        offered = [a for a in view["available_actions"] + view.get("recovery_actions", [])]
        names = list(names)
        for name in names:
            for a in offered:
                if a["command"] == name and a.get("enabled", True):
                    return dict(a)
        blocked = {b["command"]: b["reason"] for b in view.get("blocked_actions", [])}
        why = "; ".join(f"{n}: {blocked[n]}" for n in names if n in blocked)
        raise NotOffered(
            f"none of {names} offered to {self.role} at {view['state']}/{view['step']}"
            + (f" (blocked: {why})" if why else "")
        )

    def offers(self, names: Iterable[str]) -> bool:
        try:
            self.find(names)
            return True
        except NotOffered:
            return False

    def act(
        self, names: Iterable[str] | str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        names = [names] if isinstance(names, str) else list(names)
        view = self.view()
        action = self.find(names, view)
        body = {
            "idempotency_key": action["idempotency_key"],  # server-supplied, echoed as given
            "expected_case_version": view["case_version"],
            "payload": {**action.get("payload_defaults", {}), **(payload or {})},
        }
        r = self.http.post(f"/api/cases/{CASE}/commands/{action['command']}", json=body)
        check(
            r.status_code == 200,
            f"{action['command']} as {self.role} -> {r.status_code} {r.text[:300]}",
        )
        out = dict(r.json())
        self.posted.append(action["command"])
        return out

    def post_route(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = self.http.post(path, json=body)
        if r.status_code in (404, 405) and "detail" in r.text and "Not Found" in r.text:
            raise NotOffered(f"POST {path} -> {r.status_code}")
        check(r.status_code in (200, 201), f"POST {path} -> {r.status_code} {r.text[:300]}")
        return dict(r.json())

    def wait(self, pred: Callable[[], bool], what: str, seconds: float = 90.0) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if pred():
                return
            time.sleep(0.5)
        raise StageFailed(f"timed out after {seconds:.0f}s waiting for {what} (is the worker up?)")


# ---- stages -------------------------------------------------------------------------------


def s1_report(v: Vera, st: Stage) -> None:
    view = v.view()
    check(view["state"] == "reported", f"expected reported, got {view['state']}/{view['step']}")
    ev = v.events()
    rec = [e for e in ev if e["type"] == "report.received"]
    check(bool(rec), "no report.received event")
    t = view["transaction"]
    check(t["merchant"] == "Northstar Equipment" and t["amount_cents"] == 284000, f"txn {t}")
    st.note(f"{view['state']}/{view['step']} v{view['case_version']}")
    st.note(f"{t['merchant']} {t['amount_cents'] / 100:,.2f} {t['currency']}")
    st.note(f"report.received by {rec[0]['actor_name']} {rec[0]['record_ids']}")


def s2_open(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    out = v.act("open_case")
    c = out["case"]
    check(c["state"] == "investigating", f"after open: {c['state']}/{c['step']}")
    check(c["owner"]["name"] == "Sam Rivera", f"owner {c['owner']}")
    st.note(
        f"open_case -> {c['state']}/{c['step']} v{c['case_version']} owner {c['owner']['name']}"
    )
    st.note(f"events {[e for e in v.event_types() if e.startswith('case.')]}")


def s3_investigation(v: Vera, st: Stage) -> None:
    out = v.act("start_investigation")
    st.note(f"start_investigation -> mode {out['result'].get('mode')}")

    def settled() -> bool:
        runs = v.runs()
        return bool(runs) and runs[-1]["status"] not in ("queued", "running")

    v.wait(settled, "the investigation run to finish")
    run = v.runs()[-1]
    steps = run["steps"]
    names = {s["specialist"] for s in steps}
    st.note(f"run {run['status']} mode {run['mode']} wf v{run['workflow_version']}")
    for s in sorted(steps, key=lambda s: s["specialist"]):
        st.note(f"{s['specialist']}: {s['status']} ({s['execution_mode']}, {s['model_id']})")
    check(names == SPECIALISTS, f"specialists {sorted(names)}")
    bad = [s for s in steps if s["status"] != "succeeded"]
    check(not bad, f"steps not succeeded: {[(s['specialist'], s['failure_reason']) for s in bad]}")
    check(run["status"] == "succeeded", f"run status {run['status']}")
    c = v.view()
    st.note(f"case now {c['state']}/{c['step']} v{c['case_version']}")


def s4_evidence_policy(v: Vera, st: Stage) -> None:
    ev = v.get(f"/api/cases/{CASE}/evidence")
    recs = {r["record_id"]: r["status"] for r in ev["records"]}
    st.note(f"{len(recs)} records; missing {ev['missing']}; conflicts {len(ev['open_conflicts'])}")
    st.note(" ".join(f"{k}={s}" for k, s in sorted(recs.items())))
    check("CHG-1042" in recs and "PO-219" in recs and "DLV-882" in recs, f"records {recs}")
    if v.offers(["evaluate_policy"]):
        v.act("evaluate_policy")
    pol = v.view().get("policy")
    check(pol is not None, "case view has no policy result after evaluate_policy")
    st.note("policy " + _policy_brief(pol))
    # Business rule: with conflicting purchase records and no receipt, credit is not allowed.
    check(pol["status"] == "blocked", f"policy should block credit here, got {pol['status']}")


def _policy_brief(pol: dict[str, Any]) -> str:
    failed = ",".join(pol.get("rules_failed", []))
    return f"{pol.get('label')} (v{pol.get('policy_version')}); failed: {failed}"


# Stages 5..15 depend on backend tickets merging in parallel. Each is driven only by what the
# server offers; `generic` posts the first offered command from the list and records the step.
def generic(role: str, commands: list[str], payload: dict[str, Any] | None = None) -> Any:
    def run(v: Vera, st: Stage) -> None:
        v.as_role(role)
        before = len(v.events())
        out = v.act(commands, payload)
        c = out["case"]
        new = [e["type"] for e in v.events()[before:]]
        st.note(f"{v.posted[-1]} as {role} -> {c['state']}/{c['step']} v{c['case_version']}")
        st.note(f"events {new}")

    return run


STAGES: list[tuple[str, Callable[[Vera, Stage], None]]] = [
    ("report received", s1_report),
    ("open", s2_open),
    ("investigation (3 specialists)", s3_investigation),
    ("evidence + policy", s4_evidence_policy),
    ("follow-up draft/approve/send", generic("analyst", ["draft_followup", "draft_communication"])),
    ("cardholder reply + receipt", generic("cardholder", ["respond_to_request"])),
    ("response review", generic("analyst", ["review_response", "accept_response"])),
    ("identity verification (OTP)", generic("analyst", ["start_verification", "send_otp"])),
    ("callback with approved questions", generic("analyst", ["start_callback"])),
    ("decision packet", generic("analyst", ["prepare_decision", "submit_for_review"])),
    ("reviewer approval", generic("reviewer", ["approve_decision", "approve"])),
    ("provisional credit (once)", generic("analyst", ["issue_provisional_credit", "issue_credit"])),
    ("dispute + card controls", generic("card_admin", ["apply_card_controls", "open_dispute"])),
    ("final message", generic("analyst", ["send_final_message"])),
    ("closure checklist + close", generic("analyst", ["close_case"])),
]


def s16_audit(v: Vera, st: Stage, before: dict[str, Any]) -> None:
    v.as_role("analyst")
    ev = v.events()
    types = [e["type"] for e in ev]
    st.note(f"{len(ev)} activity events; types {sorted(set(types))}")
    actors = sorted({f"{e['actor_name']} ({e['actor_role']})" for e in ev})
    st.note(f"actors {actors}")
    after = v.get("/api/cases/summary")
    for k in ("gross_exposure", "net_exposure", "temporary_credit", "confirmed_recoveries"):
        if k in before and k in after:
            b, a = before[k]["amount_cents"] / 100, after[k]["amount_cents"] / 100
            st.note(f"{k}: {b:,.2f} -> {a:,.2f}")
    imp = v.view()["charge_impact"]
    st.note(
        "CHG-1042 impact: exposure {:,.2f} temp credit {:,.2f} net {:,.2f} ({})".format(
            imp["exposure_cents"] / 100,
            imp["temporary_credit_cents"] / 100,
            imp["net_exposure_cents"] / 100,
            imp["note"],
        )
    )
    check(types[:2] == ["report.received", "case.created"], f"feed starts {types[:2]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8300")
    ap.add_argument("--no-reset", action="store_true", help="do not POST /api/demo/reset first")
    ap.add_argument("--json", action="store_true", help="also print the table as JSON")
    args = ap.parse_args(argv)

    v = Vera(args.base)
    check(v.get("/api/health")["status"] == "ok", "API not healthy")
    if not args.no_reset:
        r = v.http.post("/api/demo/reset")
        check(r.status_code == 200, f"demo reset -> {r.status_code}")
    sess = v.as_role("analyst")
    check(sess["environment"] == "synthetic", f"environment {sess['environment']}")
    before = v.get("/api/cases/summary")

    stages = [Stage(i + 1, name) for i, (name, _) in enumerate(STAGES)]
    stages.append(Stage(16, "audit trail + exposure before/after"))
    failed = False
    stopped_at: Stage | None = None
    for st, (_, fn) in zip(stages, STAGES, strict=False):
        try:
            fn(v, st)
            st.status = "PASS"
        except NotOffered as exc:
            st.status = "NOT OFFERED"
            st.note(str(exc))
            stopped_at = st
            break
        except StageFailed as exc:
            st.status = "FAIL"
            st.note(str(exc))
            failed = True
            stopped_at = st
            break
    try:
        s16_audit(v, stages[-1], before)
        stages[-1].status = "PASS"
    except (StageFailed, NotOffered) as exc:
        stages[-1].status = "FAIL"
        stages[-1].note(str(exc))
        failed = True

    print(f"Vera demo journey  base={args.base}  case={CASE}  environment={sess['environment']}")
    print(f"{'#':>2}  {'stage':<36} {'reached?':<12} evidence")
    print("-" * 100)
    for st in stages:
        lines = st.evidence or ["-"]
        print(f"{st.num:>2}  {st.name:<36} {st.status:<12} {lines[0]}")
        for line in lines[1:]:
            print(f"{'':>2}  {'':<36} {'':<12} {line}")
    not_avail = [s.num for s in stages if s.status in ("NOT OFFERED", "not reached")]
    print("-" * 100)
    if stopped_at is not None and stopped_at.status == "NOT OFFERED":
        print(f"Stopped honestly at stage {stopped_at.num}: the server does not offer it yet.")
    print(f"Stages not available: {not_avail or 'none'}")
    print("RESULT:", "FAIL" if failed else "PASS (every offered stage passed)")
    if args.json:
        print(json.dumps([st.__dict__ for st in stages], indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
