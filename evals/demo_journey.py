"""Scripted end-to-end demo journey for CHG-1042 over HTTP, as the real demo roles.

    uv run python evals/demo_journey.py --base http://127.0.0.1:8300 [--no-reset] [--json]

Rules this script keeps (so it proves the product, not itself):
- It only talks HTTP to a running API (infra/demo.sh up). It never touches the database.
- It never builds idempotency keys: every command is posted with the `idempotency_key` and
  `payload_defaults` the case view advertises on the action (available_actions /
  recovery_actions). User-entered fields are merged over payload_defaults, as the UI does.
- Roles are switched with POST /api/session/role (demo-only route, synthetic environment).
- Investigation work is done by the real worker process; the script polls /runs.
- It drives the canonical journey through closure with the real commands: follow-up, the
  cardholder's reply with a receipt, response review, OTP identity verification (code read from
  the cardholder outbox), the verification call, related-charge review, an eligible policy
  result, packet, decision, reviewer approval, provisional credit, dispute, card controls, final
  message and close. It STOPS HONESTLY at the first stage whose commands or routes are not
  offered, then prints a readiness table. Stage 16 (audit trail and exposure) always runs
  because it only reads.

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
    """The server does not offer this stage's command or route."""


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
        # Background specialists (dispute narrative, prevention plan) may record results in
        # between: reload and retry, as the UI does after its "case changed" notice.
        for attempt in range(5):
            if attempt:
                time.sleep(1.0)
            view = self.view()
            action = self.find(names, view)
            body = {
                "idempotency_key": action["idempotency_key"],  # server-supplied, echoed as given
                "expected_case_version": view["case_version"],
                "payload": {**action.get("payload_defaults", {}), **(payload or {})},
            }
            r = self.http.post(f"/api/cases/{CASE}/commands/{action['command']}", json=body)
            if r.status_code != 409 or r.json().get("code") != "stale_case_version":
                break
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
    v.act("evaluate_policy")
    pol = v.view().get("policy")
    check(pol is not None, "case view has no policy result after evaluate_policy")
    assert pol is not None
    st.note("policy " + _policy_brief(pol))
    # Business rule: with conflicting purchase records and no receipt, credit is not allowed.
    check(pol["status"] == "blocked", f"policy should block credit here, got {pol['status']}")


def _policy_brief(pol: dict[str, Any]) -> str:
    failed = ",".join(pol.get("rules_failed", []))
    return f"{pol.get('label')} (v{pol.get('policy_version')}); failed: {failed or 'none'}"


def _moved(v: Vera, st: Stage, before: int, what: str) -> dict[str, Any]:
    c = v.view()
    new = [e["type"] for e in v.events()[before:]]
    st.note(f"{what} -> {c['state']}/{c['step']} v{c['case_version']}")
    st.note(f"events {new}")
    return c


def _at(v: Vera, step: str, what: str, seconds: float = 90.0) -> None:
    """Wait for the worker to move the case to `step` (the view is the only source)."""
    v.wait(lambda: v.view()["step"] == step, what, seconds)


def s5_follow_up(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    v.act("draft_follow_up")
    v.wait(lambda: v.offers(["send_communication"]), "the follow-up draft (worker)")
    comms = v.get(f"/api/cases/{CASE}/communications")
    check(len(comms) == 1 and comms[0]["status"] == "drafted", f"communications {comms}")
    draft = v.get(f"/api/cases/{CASE}/communications/{comms[0]['id']}")
    st.note(f"{draft['id']} drafted: {draft['subject']!r}, {len(draft['questions'])} question(s)")
    out = v.act("send_communication", {"channel": "email", "subject": draft["subject"]})
    check(out["result"]["delivery"]["status"] == "delivered", f"delivery {out['result']}")
    c = _moved(v, st, before, "draft_follow_up, send_communication")
    check(c["step"] == "waiting", f"after send: {c['step']}")


RECEIPT = {
    "file_name": "northstar-receipt.pdf",
    "content_type": "application/pdf",
    "size_bytes": 48213,
    "sha256": "4f" * 32,
}


def s6_reply(v: Vera, st: Stage) -> None:
    v.as_role("analyst")  # the activity feed is staff-only
    before = len(v.events())
    v.as_role("cardholder")
    reqs = v.get("/api/requests")["requests"]
    check(len(reqs) == 1 and not reqs[0]["responded"], f"cardholder requests {reqs}")
    rid = reqs[0]["request_id"]
    # The canonical reply (the response reviewer's reference recording reads this text).
    text = "Attached is the Northstar receipt. I placed this order for the warehouse myself."
    out = v.post_route(f"/api/requests/{rid}/responses", {"text": text, "attachment": RECEIPT})
    check(out["received"] is True, f"response {out}")
    v.as_role("analyst")
    _at(v, "response", "the reply to be stored")
    v.wait(
        lambda: v.runs()[-1]["status"] not in ("queued", "running"),
        "the response reviewer (worker)",
    )
    recs = {r["record_id"]: r["status"] for r in v.get(f"/api/cases/{CASE}/evidence")["records"]}
    receipt = next((k for k in recs if k.startswith("RCP-")), None)
    check(receipt is not None and recs[receipt] == "pending_review", f"receipt {recs}")
    st.note(f"{rid} answered; receipt {receipt} {recs[receipt]}")
    _moved(v, st, before, "submit_cardholder_response (cardholder)")


def s7_review(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    v.act(
        "review_cardholder_response",
        {
            "outcome": "conflicting",
            "note": "The reply contradicts the initial report; the receipt itself is accepted.",
            "receipt_accepted": True,
        },
    )
    recs = {r["record_id"]: r["status"] for r in v.get(f"/api/cases/{CASE}/evidence")["records"]}
    receipt = next(k for k in recs if k.startswith("RCP-"))
    check(recs[receipt] == "supporting", f"receipt not accepted: {recs}")
    # The reply contradicts the report: REP-1042 is cited by the open conflict until the call.
    check(recs["REP-1042"] == "conflicting", f"report not marked as contested: {recs}")
    st.note(f"{receipt}={recs[receipt]} REP-1042={recs['REP-1042']}")
    c = _moved(v, st, before, "review_cardholder_response conflicting")
    check(c["step"] == "idv", f"after review: {c['step']}")


def s8_identity(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    out = v.act("send_verification_request", {"channel": "otp"})
    vid = out["result"]["verification_id"]
    v.as_role("cardholder")
    box = v.get(f"/api/verifications/{vid}/outbox")
    st.note(f"{vid} sent; cardholder outbox has a {len(box['code'])}-digit code")
    view = v.view()
    action = v.find(["submit_otp"], view)
    r = v.http.post(
        f"/api/verifications/{vid}/submit_otp",
        json={
            "idempotency_key": action["idempotency_key"],
            "expected_case_version": view["case_version"],
            "code": box["code"],
        },
    )
    check(r.status_code == 200, f"submit_otp -> {r.status_code} {r.text[:300]}")
    check(r.json()["result"]["status"] == "verified", f"otp result {r.json()['result']}")
    v.posted.append("submit_otp")
    v.as_role("analyst")
    c = _moved(v, st, before, "send_verification_request, submit_otp (cardholder)")
    check(c["step"] == "verify", f"after OTP: {c['step']}")


def s9_callback(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    # The approved questions are the server's default set (payload_defaults), as the UI offers.
    out = v.act("start_callback", {"consent_recorded": True})
    cid = out["result"]["callback_id"]
    _at(v, "packet", "the verification call and the Live Verification Agent (worker)")
    call = v.get(f"/api/cases/{CASE}/callbacks/{cid}")
    res = call["result"]
    check(res is not None and res["result"] == "confirmed", f"callback {call['status']} {res}")
    st.note(f"{cid}: {call['status']}, authorization {res['authorization_answer']}")
    ev = v.get(f"/api/cases/{CASE}/evidence")
    check(ev["open_conflicts"] == [], f"open conflicts after the call {ev['open_conflicts']}")
    resolved = [f["finding_id"] for f in ev["findings"] if f["resolved_by"] == cid]
    st.note(f"conflicts resolved by {cid}: {resolved}")
    _moved(v, st, before, "start_callback")


def s10_related(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    recs = v.get(f"/api/cases/{CASE}/evidence")["records"]
    pending = [
        r["record_id"]
        for r in recs
        if r["kind"] == "related_charge" and r["status"] == "pending_review"
    ]
    check(sorted(pending) == ["CHG-1048", "CHG-1051"], f"pending related charges {pending}")
    reasons = {
        "CHG-1051": "Separate Northstar order on its own PO; not part of this charge.",
        "CHG-1048": "Cleared last month; unrelated amount.",
    }
    for rid in sorted(pending, reverse=True):
        v.act(
            "review_related_charge",
            {"record_id": rid, "decision": "not_related", "reason": reasons[rid]},
        )
    recs = {r["record_id"]: r["status"] for r in v.get(f"/api/cases/{CASE}/evidence")["records"]}
    check(not [k for k, s in recs.items() if s == "pending_review"], f"still pending {recs}")
    v.act("evaluate_policy")
    pol = v.view()["policy"]
    st.note("policy " + _policy_brief(pol))
    check(pol["status"] == "eligible", f"policy should be eligible now, got {pol['status']}")
    _moved(v, st, before, "review_related_charge x2, evaluate_policy")


def s11_packet(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    v.act("create_decision_packet")
    _at(v, "decide", "the decision packet (worker)")
    pkt = v.get(f"/api/cases/{CASE}/decision-packet")
    check(pkt["current"] and pkt["packet_status"] == "ready", f"packet {pkt['packet_status']}")
    st.note(f"packet v{pkt['version']} ready; recommendation {pkt['recommendation']!r}")
    v.act(
        "record_decision",
        {
            "decision": "credit",
            "rationale": "Cardholder confirmed on the call that she did not authorize the charge.",
        },
    )
    v.act("request_reviewer_approval")
    c = _moved(v, st, before, "create_decision_packet, record_decision credit, request approval")
    check(c["step"] == "waitrv", f"after request: {c['step']}")


def s12_approval(v: Vera, st: Stage) -> None:
    v.as_role("reviewer")
    before = len(v.events())
    v.act("approve_decision")
    c = _moved(v, st, before, "approve_decision (reviewer)")
    check(c["step"] == "issue", f"after approval: {c['step']}")


def s13_credit(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    out = v.act("issue_provisional_credit")
    st.note(f"result {json.dumps(out['result'])[:160]}")
    c = _moved(v, st, before, "issue_provisional_credit")
    check(c["charge_impact"]["temporary_credit_cents"] > 0, f"impact {c['charge_impact']}")


def s14_dispute_controls(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    for name in (
        "prepare_dispute_packet",
        "open_dispute_packet",
        "review_dispute_packet",
        "submit_dispute",
    ):
        v.act(name)
    v.act("propose_card_controls", {"controls": ["lock", "replace"]})
    v.as_role("card_admin")
    v.act("approve_card_controls")
    v.act("apply_card_controls")
    v.as_role("analyst")
    c = _moved(v, st, before, "dispute x4, propose/approve/apply card controls")
    check(c["step"] == "finalprep", f"after both tracks: {c['step']}")


def s15_final_close(v: Vera, st: Stage) -> None:
    v.as_role("analyst")
    before = len(v.events())
    v.act("draft_final_message")
    v.act("send_final_message")
    checklist = v.get(f"/api/cases/{CASE}/closure-checklist")
    st.note(f"closure checklist {json.dumps(checklist)[:160]}")
    v.act(
        "close_case",
        {"outcome": "resolved", "reason": "Provisional credit issued; dispute submitted."},
    )
    c = _moved(v, st, before, "draft/send final message, close_case")
    check(c["state"] in ("closed", "monitoring"), f"after close: {c['state']}/{c['step']}")


STAGES: list[tuple[str, Callable[[Vera, Stage], None]]] = [
    ("report received", s1_report),
    ("open", s2_open),
    ("investigation (3 specialists)", s3_investigation),
    ("evidence + policy", s4_evidence_policy),
    ("follow-up draft/approve/send", s5_follow_up),
    ("cardholder reply + receipt", s6_reply),
    ("response review", s7_review),
    ("identity verification (OTP)", s8_identity),
    ("callback with approved questions", s9_callback),
    ("related charges + policy eligible", s10_related),
    ("decision packet + credit decision", s11_packet),
    ("reviewer approval", s12_approval),
    ("provisional credit (once)", s13_credit),
    ("dispute + card controls", s14_dispute_controls),
    ("final message + close", s15_final_close),
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
