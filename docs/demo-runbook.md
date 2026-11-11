# Vera demo — recording runbook

Case `CHG-1042` · Northstar Equipment · $2,840.00 · card ••4418 · cardholder Priya Shah ·
analyst Sam Rivera · reviewer / card admin Dana Okafor. Story order follows
`apps/web/prototype/Main.dc.html` and `docs/spec/Vera_ToSpec.md` §5.1.
Stage-by-stage readiness from a real scripted run: `docs/demo-readiness.md`.

## Prerequisites
- Postgres on 127.0.0.1:54329 (`infra/dev-db.sh start` if it is not already running), `uv sync`.
- Ports 8300 (API) and 3300 (web) free. Override: `VERA_DEMO_API_PORT`, `VERA_DEMO_WEB_PORT`, `VERA_DEMO_DB`.
- Node 22 (first `up` runs `npm ci` and `next build`, ~1–2 min).

## Start, reset, stop
```
infra/demo.sh up        # REPLAY: migrate vera_demo, start API+worker+web, seed, print URL
infra/demo.sh reset     # between takes: fresh seed, runs/jobs/checkpoints cleared, worker restarted
infra/demo.sh status    # pids, health, environment, CHG-1042 state
infra/demo.sh down      # stops only what demo.sh started; Postgres keeps running
NVIDIA_API_KEY=… infra/demo.sh live   # LIVE specialists (export the key yourself; script never reads files)
```
Pre-flight before each take: `infra/demo.sh reset && uv run python evals/demo_journey.py --base http://127.0.0.1:8300`
(the journey proves every stage, then **run `infra/demo.sh reset` again** so the UI starts from intake).

## Click path (say one line per screen)
| # | Role | Screen / action | Say |
|---|---|---|---|
| 1 | Sam (analyst) | Cases queue; point at the exposure strip and the CHG-1042 row ("New report") | "A cardholder just reported a $2,840 charge she doesn't recognize; Vera opened a case and it's on Sam's queue." |
| 2 | Sam | Open CHG-1042 → **Open case** | "Sam takes ownership; every action is a typed command with an audit event." |
| 3 | Sam | **Start investigation**; watch three specialists finish (Charge, Related transactions, Receipt/Document) | "Three specialists compare the charge, PO-219 and DLV-882, and find related charges — they write findings, not decisions." |
| 4 | Sam | Evidence register: PO-219 = 1 unit $2,400, DLV-882 = 2 units, receipt missing; Policy panel = **Blocked · evidence conflict** | "The deterministic policy controller blocks credit: records disagree, the receipt is missing, identity isn't verified." |
| 5 | Sam | Follow-up draft (MSG-2201) → review → **Send** | "Vera drafts a focused request; nothing goes out until Sam sends it." |
| 6 | Switch → **Priya (cardholder)** | Cardholder request view: answer, attach receipt (MSG-2251) → Submit | "Priya only sees her request — no internal evidence." |
| 7 | Switch → Sam | Response review: receipt classified, remaining gap | "The reply is a separate record; a conflict with the first report becomes a finding, not an overwrite." |
| 8 | Sam → Priya → Sam | Identity verification: one-time code delivered to the cardholder-only outbox (simulated) | "Verification is structured; the code is only visible to the cardholder." |
| 9 | Sam | Approve callback questions → simulated callback CALL-1042 → structured result | "Sam approves the exact questions; the callback result is recorded as structured fields." |
| 10 | Sam | Decision packet PKT-1042 → Submit for review; policy re-evaluated | "The packet is bound to this evidence snapshot, policy v1 and workflow v3." |
| 11 | Switch → **Dana (reviewer)** | Reviewer decision → **Approve** | "Dana approves this exact evidence. If evidence changes, the approval goes stale." |
| 12 | Switch → Sam | **Issue provisional credit** (CREDIT-1042) | "Credit is a simulated adapter call, keyed so it can only happen once — retry replays the same result." |
| 13 | Sam / **Dana (card admin)** | Dispute DSP-1042; card controls CTL-1042 recommended → card admin applies | "Dispute and controls are separate tracks; controls need the card admin." |
| 14 | Switch → Sam | Final message to Priya → Send | "One concise closing message, sent once." |
| 15 | Sam | Closure checklist → **Close** (or Monitoring while the dispute is open) | "Close is only offered when the checklist is complete." |
| 16 | Sam | Activity feed + queue exposure strip | "Every step, actor and record id is in the audit trail; temporary credit is shown but never deducted from net exposure." |

Role switches: analyst → cardholder (step 6, and for the OTP in 8) → analyst → reviewer (11) →
analyst (12) → card admin (13) → analyst (14–16). Use the role switcher in the top bar (demo only).

## Where the real business rules show
- **Policy blocks credit** until evidence is complete: Policy panel `Blocked · evidence conflict` with failed rules
  (`purchase_records_agree`, `receipt_required_above_threshold`, `cardholder_authenticated`, …); the credit command is absent or blocked with a reason.
- **Approval bound to the evidence snapshot**: pins show `sha256:…`, policy v1, workflow v3. A material change
  (`POST /api/demo/material-change`, DLV-882 received quantity 2→1) makes checks stale and an existing approval
  "Approval out of date" (409 `approval_stale` on credit).
- **Credit exactly once**: the credit key is a business key; clicking again / retrying replays the stored result, no second credit.
- **Closure checklist**: close is only offered when every item is done.

## What is simulated (and how it is labelled)
- Environment pill **synthetic** (`/api/session` → `environment: synthetic`). No funds move; no real cardholder.
- Messaging, verification (OTP), telephony (callback), credit, dispute and card-control are **simulated adapters**;
  each call writes an adapter execution record (`adapter.succeeded|failed|uncertain` in the feed).
- REPLAY specialists use hand-authored reference recordings; steps show model `authored-reference`, mode `replay`.
- Fault injection (`POST /api/demo/adapter-fault`) and material change are demo-only routes.

## Do NOT claim on camera
- That a real model provider was called — unless you ran `infra/demo.sh live` and the run shows mode `live`.
  LIVE has never been exercised against the real provider before the recording.
- That anything is deployed, connected to a card network, bank, phone or email system.
- That the specialists "decide" — the policy controller and humans decide.

## 60-second fallback (only what is on main today)
Queue → open CHG-1042 → **Open case** → **Start investigation** (three specialists, `authored-reference`) →
Evidence register (PO-219 vs DLV-882, receipt missing) → **Evaluate policy** → `Blocked · evidence conflict` →
material change: `curl -X POST localhost:8300/api/demo/material-change -H 'content-type: application/json' -d '{}'`
→ refresh: DLV-882 v2, affected checks stale → re-evaluate policy. Then the activity feed.

## Troubleshooting
- **Investigation never finishes** → worker not running: `infra/demo.sh status`; `tail /tmp/vera-demo/worker.log`;
  `infra/demo.sh down && infra/demo.sh up`. (Do not start the worker with `python -m vera_api.worker`; see readiness notes.)
- **Port in use** → `infra/demo.sh status`; another process owns it: set `VERA_DEMO_API_PORT`/`VERA_DEMO_WEB_PORT`.
- **Stale or odd state** → `infra/demo.sh reset` (never edit the database by hand).
- **Web build failed** → `tail -30 /tmp/vera-demo/web-build.log`; backend-only: `VERA_DEMO_SKIP_WEB=1 infra/demo.sh up`.
- **UI shows old code** → `VERA_DEMO_REBUILD=1 infra/demo.sh up` after `down`.
- Logs: `/tmp/vera-demo/{api,worker,web,migrate,web-build}.log`.
