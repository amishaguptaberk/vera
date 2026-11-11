# VER-003A — Specialist runner, model client seam and LangGraph worker

First half of VER-003. The ticket stays open until VER-003B (three specialists, `start_investigation`) lands.

| | |
|---|---|
| Status | Merged; parent ticket VER-003 not yet done |
| Branch / commits | `ticket/VER-003A` `8f9acb8` (build), `f0e6c57` (session-cookie fix), `fb062af` (review repairs); merged as `1199e3e` |
| Verifier | Independent reviewer agent (read-only), one round, on `8f9acb8` |
| Verdict | repair_required (implementation): two findings. Repairs **not re-reviewed** (deadline rule); made test-first by an Opus builder and checked by the orchestrator on main. |

## Checks on main after merge (orchestrator)

ruff, format, mypy clean; migrations up/down/up from empty; pytest 216 passed at merge (246 after VER-004).

## Reviewer results (on the build commit)

- Met: scope violations recorded; crash resume without duplicate steps or events; a LIVE failure is never replaced by a recording; missing recording is an error; runner writes no case state; runs endpoint shape.
- Key hygiene clean: a sentinel key never appeared in errors, DEBUG logs, client repr, step rows, events or job errors.
- Finding 1: LIVE tool-call turns were sent in an internal format an OpenAI-compatible API rejects. Fixed (`fb062af`), with a test over a stub transport asserting wire format.
- Finding 2: grounding accepted wrong values ("28,40" = 2840, "0042" = "42", True = 1, "1e3" = "1000"). Fixed with strict Decimal comparison and negative tests.

## Also fixed in this branch

- **Session cookie bug (pre-existing, exposed by a new transitive dependency):** with two session cookies on a request, the server trusted the last one even if another was tampered. Now exactly one valid cookie is required; otherwise no session (demo user in synthetic, 401 elsewhere). Three new tests.
- Step success is re-checked under lock so two workers cannot both apply a step; job heartbeat; an unset execution mode outside tests is an error, never a silent replay.

## Known limitations

- **No real call to the NVIDIA API has ever been made**: the build workspace cannot reach it. LIVE is tested against stub transports only. The capability probe and recording CLI must be run on a networked machine.
- Repair commits not independently reviewed.
- An interrupted LIVE step calls the model again on resume (cost, no duplicates).
- `GET /api/cases/{id}/runs` needs no session.
- Env var name is `VERA_BASE_URL`; the plan says `VERA_MODEL_BASE_URL`.
