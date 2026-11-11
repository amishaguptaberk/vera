# Vera demo — recording runbook

**Seeded scenario:** `CHG-1042` · Northstar Equipment · $2,840.00 · card ••4418 · posted Nov 8 ·
PO-219 approves 1 unit for $2,400 · DLV-882 records 2 units · REP-1042 "I do not recognize this
charge." · related CHG-1051 ($1,200) and CHG-1048 ($620). Five display-only example rows fill the
queue (CHG-1029/1033/1036/1039/1051), as in the prototype.

```
infra/demo.sh up        # REPLAY · db vera_demo · migrate · API :8300 + worker + web :3300 · seed · prints URL
infra/demo.sh reset     # between takes: fresh seed; runs, jobs, checkpoints and feature tables cleared; worker restarted
infra/demo.sh status    # pids, health, environment, mode, CHG-1042 state
infra/demo.sh down      # stops only what demo.sh started (pidfiles in /tmp/vera-demo); Postgres keeps running
NVIDIA_API_KEY=… infra/demo.sh live   # LIVE specialists; refuses to start without the exported key
```
Before the frontend branch is on main: `VERA_DEMO_WEB_DIR=<dir with ticket/VER-012-F1 apps/web> infra/demo.sh up`.
The top-bar **Reset** button (synthetic only) is the same `POST /api/demo/reset`; prefer `infra/demo.sh reset` between takes.

**Demo accounts (no login; role switcher "Viewing as …" in the top bar, demo only):**
Finance analyst = **Sam Rivera** (analyst, ops admin) · Reviewer · card admin = **Dana Okafor** ·
Cardholder = **Priya Shah**. Switch only where the path says so.

## Pre-flight checklist (every take)
1. `infra/demo.sh status` → api, worker, web `running`; `mode: replay`; `API health: ok`; `CHG-1042: reported / intake v1`.
2. Optional proof run: `uv run python evals/demo_journey.py --base http://127.0.0.1:8300` → `RESULT: PASS`; then **`infra/demo.sh reset` again**.
3. Browser: Chrome, window 1440 px wide (viewport 1440×900), zoom 100%, OS "reduce motion" OFF, one tab at `http://127.0.0.1:3300/cases`.
4. Role switcher shows **Viewing as Finance analyst**; pill shows **SYNTHETIC ENVIRONMENT**.
5. Close devtools; hide the bookmarks bar.

## PATH A — fallback (verified 00:25 in headless Chrome 1440×900 on main bbe60ec + ticket/VER-012-F1 988454f)
Timings measured by a scripted browser walk (UI response after the click; add your talking time).

| # | URL / click | What appears | Say (one line) | Time |
|---|---|---|---|---|
| A1 | `localhost:3300/cases` | Queue; exposure strip: Gross $11,220 · Net $11,220 · Temporary credit $3,960 (pending) · Confirmed recoveries $0 · Due today $5,660 · Overdue $1,180; CHG-1042 row "New report" | "Six open card charges; net exposure only drops for confirmed recoveries — temporary credit never counts." | 1 s |
| A2 | Click **CHG-1042 · Northstar Equipment** | Case workspace: $2,840.00, card 4418, Priya Shah; state **New report**; Step 1 of 11 | "A cardholder reported a charge she doesn't recognise; Vera opened CHG-1042 for Sam." | 1 s |
| A3 | Click **Open case** (primary) | State **Needs investigation** | "Sam takes ownership — every button is a typed command with an audit event." | <1 s |
| A4 | Click **Start investigation**, then tab **Run details** | Run `· succeeded · REPLAY · workflow v3 · policy v1`; three steps charge_investigator, related_transaction_investigator, receipt_document_reviewer: **REPLAY · Model authored-reference (hand-authored reference recording, not a live model) · Prompt version v1** | "Three specialists ran. This take replays hand-authored reference recordings — labelled right here — not a live model." | 1–3 s (state → **Investigation complete** ~1.3 s after the click) |
| A5 | Tab **Evidence** | Register: CHG-1042, PO-219, DLV-882 **Conflicting**; REP-1042, CHG-1048, CHG-1051 Pending review; PRF-4418 Supporting; **Missing: Receipt**; **Open conflicts**: amount CHG-1042 $2,840 vs PO-219 $2,400, quantity PO-219 1 vs DLV-882 2; Findings with record citations | "Every finding cites a record and version: charged $440 over the PO, two units delivered against one approved, receipt missing." | <1 s |
| A6 | Tab **Decision** (click **Evaluate policy** first if offered) | Policy **Blocked · evidence conflict · v1**; rules failed `cardholder_authenticated, purchase_records_agree, receipt_required_above_threshold, no_pending_review, structured_verification`; evidence used list | "The deterministic policy controller — not the model — blocks credit until these rules pass." | <1 s |
| A7 | Expand **Demo controls** → **Simulate material change** | Notice "New version v2 · stale checks: purchase_records" | "Simulated source-system update: the delivery system corrects DLV-882. This button is a demo control." | 1 s |
| A8 | Tab **Evidence** → click **DLV-882** | DLV-882 **v2 current** (received_quantity 1, "delivery system (demo)"), **v1 superseded** (2) — history kept; open conflicts drop from 2 to 1 | "Nothing is overwritten: v1 is kept, the check that depended on it is marked stale." | 1 s |
| A9 | Tab **Decision** | Policy re-evaluated on the new snapshot — still **Blocked** (amount conflict, receipt, identity remain) | "Policy re-runs on the new evidence snapshot; still blocked, for the reasons that remain." | <1 s |
| A10 | **Hold for more information** → Reason "Waiting for the receipt from the cardholder", Next owner `usr-sam-rivera` → submit | State **On hold**, hold box with the reason | "Holds need a reason and an owner." | 2 s |
| A11 | **Resume** | Back to **Investigation complete** | — | 1 s |
| A12 | Scroll to **Activity** (left column, "Audit history · newest first") | ~25 rows: Sam Rivera · analyst, specialist steps, findings, policy evaluated, evidence version, hold/resume | "This is the audit trail: who, which role, what record." | — |
| A13 | **Viewing as → Cardholder** | Analyst actions gone (no Evaluate policy / Hold / Reassign) | "Priya sees no analyst controls." (**Do not** open the Decision / Run details tabs here — see caveat) | 1 s |
| A14 | **Viewing as → Finance analyst** | Analyst view back | — | up to 7 s (measured 6.8 s; wait for it) |

Caveats seen on this build (do not show on camera): as Cardholder the workspace still shows the
Decision/Run-details tabs and the policy panel (internal evidence ids) and offers **Link duplicate report**;
the sidebar **Automations** link 404s (`/automations/workflows`) — do not click it.

## PATH B — full journey (prototype order: intake → draft → waiting → response → idv → verify/callback → packet → reviewer → credit → dispute → controls → final → close)
Status: `live` = real backend + real UI (proved by `evals/demo_journey.py`, see `docs/demo-readiness.md`);
`preview` = design preview on development fixtures at `/preview/…` (built only with `VERA_PREVIEW=1`, banner
"Development fixtures — not live data") — **say "this is a design preview on fixtures"**; `not ready` = skip.

| # | Prototype screen (phase) | Role | Real route / panel | Backend commands | Status (00:27, main bbe60ec) |
|---|---|---|---|---|---|
| B1 | Cases queue + exposure strip | Sam | `/cases` | `GET /api/cases`, `/api/cases/summary` | live |
| B2 | Case intake ("New report") → Open case | Sam | `/cases/CHG-1042` | `open_case` | live |
| B3 | Investigation, 3 specialists, Run details | Sam | Run details tab | `start_investigation` + worker | live |
| B4 | Evidence register, findings, policy blocked | Sam | Evidence / Decision tabs | `evaluate_policy` | live |
| B5 | Follow-up draft MSG-2201 → review → Send ("draft" → "waiting") | Sam | Communications tab | VER-005 | not ready |
| B6 | Cardholder request: answer + attach receipt MSG-2251 / RCPT-1042 | **Priya** | cardholder request view | `POST /api/requests/{id}/responses` (VER-005) | not ready |
| B7 | Response review ("response") | Sam | Communications / Evidence | VER-005 | not ready |
| B8 | Identity check, OTP to cardholder-only outbox ("idv") | Sam → **Priya** → Sam | verification panel | VER-006 | not ready |
| B9 | Callback CALL-1042 with approved questions ("verify") | Sam | callback panel | `start_callback`, `record_callback` (VER-007) | not ready |
| B10 | Decision packet PKT-1042, Ask Vera ("packet") | Sam | Decision tab | VER-009 | not ready |
| B11 | Reviewer decision → Approve ("waitrv") | **Dana (reviewer)** | reviewer view | VER-009 | not ready |
| B12 | Issue provisional credit CREDIT-1042, exactly once ("issue") | Sam | Decision tab | VER-010 | not ready |
| B13 | Dispute DSP-1042 ("dsp_*") | Sam | dispute panel | VER-010 | not ready |
| B14 | Card controls CTL-1042 → card admin applies ("controls" → "waitctl" → "ctl_apply") | Sam → **Dana (card admin)** | controls panel | VER-010 | not ready |
| B15 | Final message ("finalprep" → "final") | Sam | Communications | VER-011 | not ready |
| B16 | Closure checklist → Close / Monitoring ("close") | Sam | case header | VER-011 | not ready |
| B17 | Activity feed + exposure after | Sam | Activity, `/cases` strip | read only | live |
| B18 | Automations / workflow graph (prototype "Automations") | Sam | `/automations` | VER-014 | not ready (link 404s) |

Role switches in Path B: analyst → **cardholder** (B6, B8 code) → analyst → **reviewer** (B11) →
analyst (B12–B13) → **card admin** (B14) → analyst (B15–B17).
Do **not** use Simulate material change before B6 in Path B (it rewrites DLV-882 to 1 unit and removes
the "second unit" story); use it only after B11 to show the approval going stale ("Approval out of date").

## Real business rules on screen
- Policy blocks credit until evidence is complete (A6/A9).
- Approval is bound to evidence snapshot + policy v1 + workflow v3; a material change after approval makes it stale (409 `approval_stale`).
- Credit uses a business key: a second click replays the stored result, no second credit.
- Close is only offered when the closure checklist is complete.

## What is simulated, and how it is labelled
- **SYNTHETIC ENVIRONMENT** pill; "No funds moved" on Charge impact. No real cardholder, bank or card network.
- Messaging, OTP, telephony, credit, dispute and card controls are **simulated adapters**; every call writes an execution record (`adapter.*` in Activity).
- REPLAY specialists: Run details says **REPLAY · authored-reference (hand-authored reference recording, not a live model)**.
- **Demo controls** (Simulate material change), Reset and the role switcher exist only in the synthetic environment.

## Do NOT claim on camera
- A real model/provider call — unless you ran `infra/demo.sh live` and Run details shows LIVE. LIVE has never been run against the real provider.
- Any deployment, or any connection to a bank, card network, phone or email.
- That specialists decide anything — the policy controller and the humans decide.
- Anything marked `preview` as working functionality.

## Troubleshooting
- **Run never finishes / "Specialists are reviewing" forever** → worker down: `infra/demo.sh status`, `tail /tmp/vera-demo/worker.log`, then `infra/demo.sh down && infra/demo.sh up`. Never start the worker with `python -m vera_api.worker` (it registers no handlers; see readiness).
- **Port in use** → `VERA_DEMO_API_PORT` / `VERA_DEMO_WEB_PORT`.
- **Odd state** → `infra/demo.sh reset`. Never edit the database by hand.
- **Web build failed** → `tail -30 /tmp/vera-demo/web-build.log`; backend only: `VERA_DEMO_SKIP_WEB=1 infra/demo.sh up`. Stale UI → `infra/demo.sh down && VERA_DEMO_REBUILD=1 infra/demo.sh up`.
- Logs: `/tmp/vera-demo/{api,worker,web,migrate,web-build}.log`.
