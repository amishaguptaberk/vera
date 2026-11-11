# VER-003B — Model-backed investigation: three specialists, start and retry

Completes VER-003 together with VER-003A.

| | |
|---|---|
| Status | Done |
| Branch / commits | `ticket/VER-003B` `7ea483c`, `86c2103` (build), `0c64476` (repair); merged to main |
| Verifier | Independent reviewer agent (read-only), one round, on `86c2103` |
| Verdict | repair_required (implementation): all eight criteria met in REPLAY; one defect. Repair **not re-reviewed** (deadline rule); test-first, checked on main. |

## Checks on main after merge

ruff, format, mypy clean (39 files); one migration head (`0008`); upgrade / downgrade base / upgrade ok; pytest **322 passed**.

## Reviewer results

- **Model-driven by construction:** a search of all non-test, non-recording code for the case's amounts, quantities and related-charge id found nothing. Prompts give record ids, kinds and field names only; values must be fetched through `read_field`.
- **One code path:** LIVE and REPLAY share the graph, runner, tool gateway, validators and write path; only the model client differs.
- **No silent substitution:** with LIVE failing (500, timeout, garbage JSON) the recordings directory was never touched; only an explicit replay retry uses a recording, labelled `replayed`.
- **End to end in REPLAY over HTTP:** six findings with record · version · field citations; three steps with `model_id` `authored-reference`; policy `blocked` (two open conflicts), not eligible; case at `investigating` / `draft`; second start replayed; reset then re-run identical.
- **RBAC:** non-analyst roles get 403 on start, retry and completion; nothing written.
- Related charge linked on transaction id, merchant and amount; a validator rejects any related-charge finding citing card digits.

## Finding and repair

- A LIVE crash after some findings were written, followed by a different model answer, failed the job three times and left the case mid-investigation with no retry action.
- Repair: the validated output is stored before it is applied, so a resume re-applies the same output without calling the model; a job that fails for good marks its step `failed` / `apply_failed` with retry and hold offered. Also: one `specialist.failed` per failed sibling; retrying one step no longer re-runs another failed sibling; demo reset clears jobs, runs and checkpoints.

## Known limitations

- **Nothing here has run against a real model.** LIVE is tested only over stub HTTP transports. Whether the real provider and model follow the tool protocol and schema is unproven. The capability probe and recording CLI have never been run.
- **REPLAY recordings are hand-written reference outputs**, labelled `authored-reference` in the files, the API and the UI. Only CHG-1042 has recordings.
- LIVE requests use `response_format: json_object` with the schema in the prompt; compliance relies on validation and retries.
- Repair commit not independently reviewed.
- A retry after `apply_failed` re-applies the stored output whatever mode is requested.
