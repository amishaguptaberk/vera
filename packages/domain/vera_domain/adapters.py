"""Adapter execution types (pure). The executor lives in vera_api.adapters."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

AdapterStatus = Literal["pending", "succeeded", "failed", "uncertain"]
FaultMode = Literal["fail", "uncertain", "timeout"]


class AdapterResult(BaseModel, frozen=True):
    """succeeded: the effect happened once. failed: nothing happened (safe to retry with the same
    key). uncertain: dispatched, response lost; only `lookup` may resolve it."""

    status: Literal["succeeded", "failed", "uncertain"]
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    execution_id: int | None = None
    replayed: bool = False


class SimulatedAdapter(Protocol):
    def call(self, operation: str, request: dict[str, Any]) -> AdapterResult: ...
