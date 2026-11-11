# Vera

Vera is a post-report investigation workspace for corporate-card charges. When a cardholder reports a charge they do not recognise, Vera opens a case, gathers the source records, runs a team of LLM agents on NVIDIA-hosted models (Llama 3.3 70B through the NVIDIA API) that read the evidence and reason over it, asks the cardholder targeted questions, verifies identity, places an analyst-approved verification call, prepares a decision packet for a reviewer, and carries the approved outcome through provisional credit, dispute, card controls, the final message and closure.

The demo case is **CHG-1042 · Bayline Industrial Supply · $2,840.00**.

[![Vera launch video](media/vera-launch-poster.jpg)](media/vera-launch.mp4)

▶ [Watch the launch video](media/vera-launch.mp4) (2:19)

## Agents, not scripts

Vera's investigation is done by nine specialist agents running on **NVIDIA-hosted models** (`meta/llama-3.3-70b-instruct` by default via `integrate.api.nvidia.com`; any NVIDIA API model can be set with `VERA_MODEL_ID`):

| Agent | What it decides |
|---|---|
| Charge Investigator | Whether the charge matches the purchase order, delivery and card records |
| Receipt Document Reviewer | Whether the receipt agrees with the order and what was received |
| Related Transaction Investigator | Which other charges at the merchant belong to the same pattern |
| Cardholder Follow-up | Which targeted questions to ask the cardholder, from the open findings |
| Response Reviewer | Whether the cardholder's reply resolves, contradicts or leaves open each finding |
| Live Verification Agent | The answers given on the verification call, grounded in the transcript |
| Decision Packet Preparer | The cited summary and recommendation a reviewer decides on |
| Dispute Packet Preparer | The network reason code and cited dispute narrative |
| Prevention Planner | Which card controls would stop a repeat |

Each agent runs a tool-calling loop: the model decides which evidence fields to read through a scoped tool gateway (up to four rounds), then returns typed findings. Every finding must cite fields the agent actually read; output that fails the schema or cites evidence it never read is rejected, and the agent is re-prompted with the reason (up to two retries).

### Orchestration with LangGraph

Workflows are data: versioned node and edge lists that compile to a LangGraph `StateGraph`, checkpointed in Postgres so a run resumes where it stopped after a worker restart. The investigation graph fans out and joins:

```
            ┌─► Charge Investigator ──────────────┐
  start ────┤                                     ├─► Receipt Document Reviewer ─► Policy check ─► end
            └─► Related Transaction Investigator ─┘
```

The verification call is a second graph that pauses on a LangGraph `interrupt` after the analyst approves the questions and the cardholder consents, and resumes only when the provider's signed webhook delivers the transcript. Follow-up questions, response review, decision and dispute packets, and the prevention plan run as jobs on a Postgres-backed queue as the case reaches each step.

The agents gather evidence and recommend; they never move money or change a case on their own. A deterministic Policy Controller and a human reviewer gate every credit, dispute and card control.

`infra/demo.sh up` starts in **replay** mode, which feeds each agent a recorded model response through the same loop and validators, so the demo is repeatable offline. `infra/demo.sh live` (with `NVIDIA_API_KEY` exported) runs the agents against the live NVIDIA endpoint.

## Architecture

```
Next.js UI ──► FastAPI command gateway ──► PostgreSQL
                   │                         ▲
                   │ role → schema → idempotency → version → step → policy → approval → effect
                   ▼                         │
            Worker (Postgres job queue) ── LangGraph (checkpointed) ── SpecialistRunner
                                                                      ├─ Model client: live | replay
                                                                      └─ Tool gateway (scoped evidence reads)
            Policy Controller (pure, deterministic)      Simulated adapters (messaging, OTP, voice, credit, dispute, card controls)
```

- Every change is a typed, role-checked, versioned, idempotent command, recorded as an audit event.
- A case's state and step are derived from stored facts by one function; nothing else writes them.
- Specialist output never changes state directly. It is validated against its schema and against the evidence it cites, then stored through service commands.
- Policy is a pure function of the evidence snapshot and the policy version. Credit requires an eligible policy result and a reviewer approval bound to the current evidence snapshot, policy version and workflow version.
- Live model failures are explicit. A recorded response is used only when an analyst retries a step in replay mode, and the step is labelled as replayed.
- One-time codes are never stored or shown to staff; only a keyed hash is kept.

## Roles in the demo

Switch with **Viewing as …** in the top bar (synthetic environment only):

| Role | Person |
|---|---|
| Finance analyst (also ops admin) | Sam Rivera |
| Reviewer, card admin | Dana Okafor |
| Cardholder | Priya Shah |

## Run the demo

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, PostgreSQL 16.

```bash
infra/dev-db.sh start      # local Postgres on 127.0.0.1:54329 (or point VERA_DATABASE_URL at your own)
infra/demo.sh up           # migrate, seed, start API :8300, worker and web :3300 in replay mode
open http://127.0.0.1:3300/cases
infra/demo.sh reset        # fresh seed between takes
infra/demo.sh down
```

If Postgres binaries are not in `/usr/lib/postgresql/16/bin`, set `VERA_PGBIN`. With Docker: `docker compose -f infra/docker-compose.yml up`.

### Live model

Replay mode uses reference recordings in `evals/recordings/` and needs no key. To run the specialists against the model provider:

```bash
export NVIDIA_API_KEY=... VERA_MODEL_ID=meta/llama-3.3-70b-instruct
uv run python -m vera_api.model_client probe
NVIDIA_API_KEY=$NVIDIA_API_KEY infra/demo.sh live
```

### Voice verification

The verification call uses an ElevenLabs voice agent over Twilio or SIP. In the synthetic environment a simulated provider drives the same webhook path. For real calls set `VERA_VOICE_PROVIDER=elevenlabs`, `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_AGENT_PHONE_NUMBER_ID`, `ELEVENLABS_WEBHOOK_SECRET` (and `ELEVENLABS_TELEPHONY=sip` for SIP trunks; Twilio is the default), configure one data-collection item per approved question on the agent, and point its post-call webhook at `<public API origin>/api/webhooks/voice/elevenlabs`.

## Configuration

See `.env.example`. Settings are read from the environment; export them before running.

## Development

```bash
uv sync
uv run ruff check . && uv run mypy packages services
uv run alembic upgrade head
uv run pytest -q
uv run python -m evals.harness        # scenario suite in replay mode

cd apps/web && npm ci
npm run typecheck && npm run lint && npm test && npm run build
```

## Repository

| Path | Contents |
|---|---|
| `packages/domain` | Domain types, commands, state derivation, policy, specialist specs |
| `services/api` | FastAPI app, command gateway, features, worker, model client |
| `infra` | Migrations, local Postgres, demo script, containers |
| `apps/web` | Next.js app; `apps/web/prototype` is the original design prototype |
| `evals` | Scenario harness and reference recordings |
| `tests` | Unit, integration, contract and scenario tests |
