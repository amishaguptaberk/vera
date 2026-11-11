"""SpecialistRunner (plan §18): one loop for LIVE and REPLAY.

typed input -> messages -> ModelClient -> tool calls through ToolGateway -> schema validation
-> grounding validation -> validated typed output handed to the caller's `apply` callback.
The runner writes only its own step row and run.step_* events; it never writes case state, and
it never substitutes one execution mode for another.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from vera_domain.clock import Clock
from vera_domain.enums import Role, RunEventType
from vera_domain.specialists import (
    ExecutionMode,
    FailureReason,
    ReadField,
    SpecialistSpec,
    StepStatus,
    validate_grounding,
)

from vera_api.intake import _emit
from vera_api.model_client import PROBE_TOOL, ModelClient, ModelError, ModelResult
from vera_api.models import Case
from vera_api.models_runs import WorkflowRun, WorkflowStep
from vera_api.tool_gateway import ScopeViolation, ToolGateway

VALIDATION_RETRIES = 2
MAX_TOOL_ROUNDS = 4

ClientFactory = Callable[[ExecutionMode, str], ModelClient]  # (mode, case_id) -> client


@dataclass(frozen=True)
class StepOutcome:
    status: str
    attempts: int
    output: BaseModel | None = None
    failure_reason: str | None = None


class _Fail(Exception):
    def __init__(self, reason: FailureReason, message: str) -> None:
        self.reason = reason
        self.message = message


def create_run(
    session: Session,
    *,
    case_id: str,
    mode: ExecutionMode,
    now: datetime,
    run_id: str | None = None,
    commit: bool = True,
) -> str:
    """Create a workflow run pinned to the case's workflow and policy versions."""
    case = session.get(Case, case_id)
    if case is None:
        raise LookupError(case_id)
    run = WorkflowRun(
        id=run_id or f"run_{uuid.uuid4().hex[:12]}",
        case_id=case_id,
        workflow_version=case.workflow_version,
        policy_version=case.policy_version,
        status="running",
        mode=mode.value,
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    if commit:
        session.commit()
    else:
        session.flush()  # inside a command transaction (start_investigation)
    return run.id


def _wire_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    """Internal {id, name, arguments: dict} -> OpenAI wire form for the assistant message."""
    return {
        "id": tc.get("id", ""),
        "type": "function",
        "function": {"name": tc["name"], "arguments": json.dumps(tc.get("arguments", {}))},
    }


class SpecialistRunner:
    def __init__(self, client_factory: ClientFactory, read_field: ReadField, clock: Clock) -> None:
        self._factory = client_factory
        self._read_field = read_field
        self._clock = clock

    def run_step(
        self,
        session: Session,
        run_id: str,
        step_key: str,
        spec: SpecialistSpec,
        inputs: BaseModel | dict[str, Any],
        mode: ExecutionMode,
        apply: Callable[[BaseModel], None] | None = None,
        heartbeat: Callable[[], object] | None = None,
    ) -> StepOutcome:
        """`heartbeat` (e.g. the worker's job touch) runs before each model call."""
        run = session.get(WorkflowRun, run_id)
        if run is None:
            raise LookupError(run_id)
        case = session.get(Case, run.case_id)
        assert case is not None
        step = session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.run_id == run_id, WorkflowStep.step_key == step_key)
            .with_for_update()
        ).first()
        if step is not None and step.status == StepStatus.SUCCEEDED:
            return StepOutcome(
                "succeeded", step.attempts, spec.output_schema.model_validate(step.output)
            )
        if (
            step is not None
            and step.output is not None
            and (
                step.status == StepStatus.RUNNING
                or step.failure_reason == FailureReason.APPLY_FAILED.value
            )
        ):
            # A validated output was stored before apply: re-apply it, never call the model again
            # (same finding ids and payloads, so the writes replay idempotently).
            return self._reapply(session, case, step, spec, mode, apply)
        typed_in = spec.input_schema.model_validate(
            inputs.model_dump() if isinstance(inputs, BaseModel) else inputs
        )
        resumed = step is not None and step.status == StepStatus.RUNNING
        if step is None:
            step = WorkflowStep(run_id=run_id, step_key=step_key, specialist=spec.name)
            session.add(step)
        step.status = StepStatus.RUNNING.value
        step.execution_mode = mode.value
        step.prompt_version = spec.prompt_version
        step.model_id = None
        step.usage = {}
        step.attempts = 0
        step.failure_reason = None
        step.error = None
        step.output = None
        step.tool_calls = []
        step.started_at = self._clock.now()
        step.finished_at = None
        if not resumed:
            self._emit(session, case, RunEventType.RUN_STEP_STARTED, spec, step_key, mode, {})
        session.commit()

        gateway = ToolGateway(spec, case.id, self._read_field)
        usage: dict[str, Any] = {}
        state: dict[str, Any] = {"attempts": 0, "model_id": None, "heartbeat": heartbeat}
        try:
            output = self._attempts(spec, typed_in, mode, case.id, gateway, usage, state)
        except _Fail as fail:
            return self._finish_failed(
                session, case, step, spec, mode, gateway, usage, state, fail.reason, fail.message
            )
        # Persist the validated output before any write, so a crash inside apply resumes from it.
        current = self._lock_step(session, run_id, step_key)
        if current.status == StepStatus.SUCCEEDED:
            stored = StepOutcome(
                "succeeded", current.attempts, spec.output_schema.model_validate(current.output)
            )
            session.rollback()
            return stored
        current.attempts = state["attempts"]
        current.model_id = state["model_id"]
        current.usage = usage
        current.output = output.model_dump(mode="json")
        current.tool_calls = gateway.calls
        session.commit()
        return self._reapply(session, case, current, spec, mode, apply)

    def _lock_step(self, session: Session, run_id: str, step_key: str) -> WorkflowStep:
        return session.scalars(
            select(WorkflowStep)
            .where(WorkflowStep.run_id == run_id, WorkflowStep.step_key == step_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).one()

    def _reapply(
        self,
        session: Session,
        case: Case,
        step: WorkflowStep,
        spec: SpecialistSpec,
        mode: ExecutionMode,
        apply: Callable[[BaseModel], None] | None,
    ) -> StepOutcome:
        """Apply the stored validated output and mark the step succeeded (at most once)."""
        run_id, step_key = step.run_id, step.step_key
        current = self._lock_step(session, run_id, step_key)
        output = spec.output_schema.model_validate(current.output)
        if current.status == StepStatus.SUCCEEDED:
            session.rollback()
            return StepOutcome("succeeded", current.attempts, output)
        try:
            if apply is not None:
                apply(output)
        except Exception:
            session.rollback()  # the step stays `running` with its output; the job retries
            raise
        current = self._lock_step(session, run_id, step_key)
        current.status = StepStatus.SUCCEEDED.value
        current.failure_reason = None
        current.error = None
        current.finished_at = self._clock.now()
        self._emit(
            session,
            case,
            RunEventType.RUN_STEP_SUCCEEDED,
            spec,
            step_key=step_key,
            mode=ExecutionMode(current.execution_mode or mode.value),
            detail={"attempts": current.attempts, "model_id": current.model_id},
        )
        session.commit()
        return StepOutcome("succeeded", current.attempts, output)

    def _attempts(
        self,
        spec: SpecialistSpec,
        typed_in: BaseModel,
        mode: ExecutionMode,
        case_id: str,
        gateway: ToolGateway,
        usage: dict[str, Any],
        state: dict[str, Any],
    ) -> BaseModel:
        client = self._factory(mode, case_id)
        messages = spec.build_messages(typed_in)
        schema = spec.output_schema.model_json_schema()
        tools = [PROBE_TOOL] if "read_field" in spec.allowed_tools else []
        last_reason = FailureReason.SCHEMA_INVALID
        last_message = ""
        for _attempt in range(VALIDATION_RETRIES + 1):
            state["attempts"] += 1
            content: dict[str, Any] = {}
            try:
                result = self._call(client, spec, messages, schema, tools, gateway, usage, state)
                content = result.content
                output = spec.output_schema.model_validate(content)
                violations = validate_grounding(spec.findings_of(output), gateway.read_field)
            except ModelError as exc:
                if exc.reason != FailureReason.SCHEMA_INVALID:
                    raise _Fail(FailureReason(exc.reason), str(exc)) from None
                last_reason, last_message = FailureReason.SCHEMA_INVALID, str(exc)
            except ValidationError as exc:
                last_reason = FailureReason.SCHEMA_INVALID
                last_message = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
                )
            except ScopeViolation as exc:
                raise _Fail(FailureReason.SCOPE_VIOLATION, str(exc)) from None
            else:
                if not violations:
                    return output
                last_reason = FailureReason.UNGROUNDED
                last_message = "; ".join(v.message for v in violations)
            messages = [
                *messages,
                {"role": "assistant", "content": json.dumps(content)},
                {
                    "role": "user",
                    "content": f"Your previous output was rejected ({last_reason.value}): "
                    f"{last_message}. Return corrected JSON only.",
                },
            ]
        raise _Fail(last_reason, last_message)

    def _call(
        self,
        client: ModelClient,
        spec: SpecialistSpec,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        tools: list[dict[str, Any]],
        gateway: ToolGateway,
        usage: dict[str, Any],
        state: dict[str, Any],
    ) -> ModelResult:
        convo = list(messages)
        result = None
        for _ in range(MAX_TOOL_ROUNDS + 1):
            if state["heartbeat"] is not None:
                state["heartbeat"]()
            result = client.complete(
                specialist=spec.name,
                prompt_version=spec.prompt_version,
                messages=convo,
                response_schema=schema,
                tools=tools,
            )
            state["model_id"] = result.model_id
            for k, v in result.usage.items():
                if isinstance(v, int | float):
                    usage[k] = usage.get(k, 0) + v
            if not result.tool_calls:
                return result
            convo.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [_wire_tool_call(tc) for tc in result.tool_calls],
                }
            )
            for tc in result.tool_calls:
                data = gateway.call(tc["name"], tc.get("arguments", {}))  # may raise ScopeViolation
                convo.append(
                    {"role": "tool", "tool_call_id": tc.get("id", ""), "content": json.dumps(data)}
                )
        assert result is not None
        return ModelResult({}, [], result.usage, result.model_id, result.mode)  # tool loop ran out

    def _finish_failed(
        self,
        session: Session,
        case: Case,
        step: WorkflowStep,
        spec: SpecialistSpec,
        mode: ExecutionMode,
        gateway: ToolGateway,
        usage: dict[str, Any],
        state: dict[str, Any],
        reason: FailureReason,
        message: str,
    ) -> StepOutcome:
        session.rollback()
        step = session.merge(step)
        step.status = StepStatus.FAILED.value
        step.failure_reason = reason.value
        step.error = message
        step.attempts = state["attempts"]
        step.model_id = state["model_id"]
        step.usage = usage
        step.tool_calls = gateway.calls
        step.finished_at = self._clock.now()
        self._emit(
            session,
            case,
            RunEventType.RUN_STEP_FAILED,
            spec,
            step.step_key,
            mode,
            {"reason": reason.value, "attempts": state["attempts"]},
        )
        session.commit()
        return StepOutcome("failed", state["attempts"], None, reason.value)

    def _emit(
        self,
        session: Session,
        case: Case,
        type_: RunEventType,
        spec: SpecialistSpec,
        step_key: str,
        mode: ExecutionMode,
        detail: dict[str, Any],
    ) -> None:
        _emit(
            session,
            type_,
            case,
            f"specialist:{spec.name}",
            Role.SPECIALIST,
            self._clock.now(),
            [case.id],
            f"{spec.name} {step_key}: {type_.value.split('_', 1)[1]}",
            {
                "step_key": step_key,
                "specialist": spec.name,
                "execution_mode": mode.value,
                "prompt_version": spec.prompt_version,
                **detail,
            },
        )
