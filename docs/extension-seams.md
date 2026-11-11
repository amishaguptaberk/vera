# Extension seams (VER-017)

How a feature ticket adds tables, commands, effects, facts, events, labels and routes **without
editing a shared file**. The only shared edit is one line: your module name in
`services/api/vera_api/plugins.py` `FEATURES`. Everything else is registered from your own module
at import time. Never edit `gateway._execute`, `facts.derive_step`, `enums.py`, `labels.py`,
`app.py`, `seed.py`, `models.py` or another feature's files.

## Signatures

```python
# vera_api.gateway
register_commands(module_name: str, *, human: Mapping[str, CommandSpec] | None = None,
                  service: Mapping[str, CommandSpec] | None = None,
                  effects: Mapping[str, Effect] | None = None,
                  after_effects: Mapping[str, AfterEffect] | None = None,
                  key_context: KeyContext | None = None) -> None
Effect      = Callable[[Session, Case, Actor, Any, datetime, EffectContext], dict[str, Any]]
AfterEffect = Callable[[Session, Case, Actor, Any, datetime, EffectContext, Outcome], None]
KeyContext  = Callable[[Session, Case, dict[str, Any]], Mapping[str, object]]
EffectContext(command: str, key: str, first_report: Report | None, extra: dict[str, Any])
register_fact_provider(provider: Callable[[Session, Case], dict[str, Any]]) -> None
facts_for(session, case) -> CaseFacts            # the only way to get facts for derive_step
set_approval_provider(provider: Callable[[Session, Case], ApprovalState | None]) -> None  # VER-009 only

# vera_domain.commands
CommandSpec(name, roles, payload_model, allowed_steps, key_template, reducer, events, label, style,
            requires_policy: frozenset[str] | None = None, requires_approval: bool = False,
            adapter: str | None = None)
ApprovalState(snapshot_hash, policy_version, workflow_version, transaction_id, approval_id, status)

# vera_domain.enums / vera_domain.labels
register_event_types(*names: str) -> None                  # "subject.verb"; duplicates raise
register_event_summaries({event_type: sentence}); register_blockers({CaseStep: text})
register_wait_kinds({CaseStep: "cardholder" | "reviewer"})
register_labels({(CaseState, CaseStep): (state_label, StateKind, next_action)})

# vera_api.plugins
register_router(router: APIRouter, synthetic_only: bool = False) -> None
register_reset_tables(tables: list[str]) -> None           # truncated by POST /api/demo/reset

# vera_api.adapters
register_adapter(name: str, adapter: SimulatedAdapter) -> None   # .call(operation, request) -> AdapterResult
execute(session, *, case_id, adapter, operation, key, request, now) -> AdapterResult
lookup(session, key, now=None) -> AdapterResult | None
inject_fault(session, adapter, operation, mode: "fail" | "uncertain" | "timeout", times=1) -> None
AdapterResult(status: "succeeded" | "failed" | "uncertain", result: dict, error, execution_id, replayed)
```

## Rules the seams enforce

- Gate order is fixed: role → schema → idempotency replay → case version → closed/step → policy
  (`requires_policy`) → approval (`requires_approval`) → key → effect → reducer → `derive_step` →
  events → after-effect. One transaction, case row locked.
- **State/step come only from `derive_step(CaseFacts)`.** A command changes the step by writing
  rows in its effect; your fact provider reads those rows; the reducer returns
  `f.model_copy(update={...})` with the same fact values. Never write `case.state`/`case.step`.
- A fact provider returns only the `CaseFacts` fields it owns (see `facts.py` docstrings). Two
  providers returning the same field, an unknown field or an out-of-vocabulary value raise.
  Facts describe the CURRENT cycle: report a superseded row as `"none"`.
- Command names are global. A duplicate, or a spec whose `events` are not registered, raises at
  import. Register event types BEFORE `register_commands`. The reducer must emit exactly
  `spec.events`, in order; emit follow-on events from an after-effect with `intake._emit`.
- `human` commands appear in `available_actions`/`blocked_actions`; `service` commands never do.
- `requires_approval=True` is blocked (`422 approval_required`, "No approval recorded") until the
  approval provider returns an `approved` state bound to the case's current `evidence_snapshot`,
  `policy_version`, `workflow_version` and `transaction_id`; stale or unbound is `409 approval_stale`.
- Adapters: `execute` is exactly-once by key. `succeeded`/`uncertain` replay the stored row and
  never call the adapter again; `failed` means nothing happened and the same key retries. An
  `uncertain` result is hidden until `lookup(key)` resolves it. It emits `adapter.succeeded|failed|
  uncertain`. Use a business key (`credit:{case_id}`), not the command key.
- Tests: every human command needs an entry via `register_test_payloads` (parity test); the
  role × command 403 matrix covers every registered command automatically.
- Tests, reducer hook: `tests/unit/test_domain_commands.py` runs every registered reducer on its
  `TEST_PAYLOADS` entry and checks it emits exactly `spec.events`. If your reducer reads
  `ctx.extra` (your effect's output), also call
  `register_reducer_extras({"your_command": {...ctx.extra...}})`. Both live in
  `tests/support/command_payloads.py` (`from command_payloads import register_test_payloads,
  register_reducer_extras` works from unit and integration tests). A registered command with no
  entry FAILS with a message naming the missing call; it is never skipped.
- Tests must not assume an empty registry (`ADAPTERS`, `FACT_PROVIDERS`, `APPROVAL_PROVIDER`):
  other features are loaded in the same process. Monkeypatch what you need and assert relatively.
- A service command lists no human role and a human command lists only human roles
  (analyst, ops_admin, reviewer, card_admin, cardholder); a mix raises at import.
- Migration: one file, your number, `down_revision = "0009"` (table in CONTRIBUTING.md).

## Worked example (`services/api/vera_api/comms.py`, ticket VER-005)

```python
from vera_domain.commands import CommandSpec, NoPayload, StepSet, EventDraft, Reduction
from vera_domain.enums import CaseState, CaseStep, Role, register_event_types
from vera_domain.labels import register_event_summaries, register_labels
from vera_domain.enums import StateKind
from vera_api import gateway, plugins
from vera_api.models_comms import Communication  # your ORM file; table from migration 0010

register_event_types("communication.sent")
register_event_summaries({"communication.sent": "Request sent to the cardholder"})
register_labels(
    {
        (CaseState.WAITING_ON_CARDHOLDER, CaseStep.WAITING): (
            "Waiting on cardholder",
            StateKind.WAITING,
            "Send reminder or reassign",
        )
    }
)


def _send_effect(session, case, actor, payload, now, ctx):  # before the reducer, same transaction
    row = Communication(case_id=case.id, status="sent", sent_at=now, sent_by=actor.user_id)
    session.add(row)
    session.flush()
    return {"communication_id": row.id}


def _reduce_send(f, p, ctx):  # pure; mirrors what the provider reads
    return Reduction(
        facts=f.model_copy(update={"followup_status": "sent"}),
        reason="Request sent",
        events=[EventDraft("communication.sent", "Request sent", [ctx.case_id])],
        result={"communication_id": ctx.extra["communication_id"]},
    )


def _facts(session, case):  # stored rows only
    row = latest_communication(session, case.id)
    return {"followup_status": row.status if row else "none"}


SEND = CommandSpec(
    "send_communication",
    frozenset({Role.ANALYST}),
    NoPayload,
    StepSet(include=frozenset({(CaseState.INVESTIGATING, CaseStep.DRAFT)})),
    "comm:{case_id}:{case_version}",
    _reduce_send,
    ("communication.sent",),
    "Send request",
    "primary",
)
gateway.register_commands(__name__, human={SEND.name: SEND}, effects={SEND.name: _send_effect})
gateway.register_fact_provider(_facts)
plugins.register_reset_tables(["communications"])
plugins.register_router(router)  # your APIRouter(prefix="/api")
# plugins.py FEATURES += "vera_api.comms"   <- the one shared line
# tests/integration/test_comms.py:
#   from command_payloads import register_test_payloads
#   register_test_payloads({"send_communication": {}})
# infra/migrations/versions/0010_comms.py: revision = "0010", down_revision = "0009"
```
