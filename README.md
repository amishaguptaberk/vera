# Vera

Vera is a post-report investigation workspace for corporate-card charges. When a cardholder reports a charge they do not recognise, Vera opens a case, gathers the source records, runs specialist agents that compare the evidence, asks the cardholder targeted questions, verifies identity, places an analyst-approved verification call, prepares a decision packet for a reviewer, and carries the approved outcome through provisional credit, dispute, card controls, the final message and closure.

The demo case is **CHG-1042 · Bayline Industrial Supply · $2,840.00**.

## How it works

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

The verification call uses an ElevenLabs voice agent over Twilio or SIP. In the synthetic environment a simulated provider drives the same webhook path. For real calls set `VERA_VOICE_PROVIDER=elevenlabs`, `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, `ELEVENLABS_AGENT_PHONE_NUMBER_ID`, `ELEVENLABS_WEBHOOK_SECRET` and `VERA_PUBLIC_BASE_URL`, configure one data-collection item per approved question on the agent, and point its post-call webhook at `$VERA_PUBLIC_BASE_URL/api/webhooks/voice/elevenlabs`.

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
