"""Per-specialist tool gateway: scope is enforced here and every call is recorded."""

from typing import Any

from vera_domain.specialists import ReadField, SpecialistSpec


class ScopeViolation(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ToolGateway:
    def __init__(self, spec: SpecialistSpec, case_id: str, read_field: ReadField) -> None:
        self.spec = spec
        self.case_id = case_id
        self._read_field = read_field
        self.calls: list[dict[str, Any]] = []  # recorded on the step, violations included

    def _check(self, tool: str, record_id: str | None) -> None:
        if tool not in self.spec.allowed_tools:
            self._violate(tool, record_id, f"tool {tool!r} is not allowed for {self.spec.name}")
        if record_id is not None and record_id not in self.spec.allowed_record_ids(self.case_id):
            self._violate(
                tool, record_id, f"record {record_id!r} is outside the scope of {self.spec.name}"
            )

    def _violate(self, tool: str, record_id: str | None, message: str) -> None:
        self.calls.append(
            {"tool": tool, "record_id": record_id, "outcome": "scope_violation", "message": message}
        )
        raise ScopeViolation(message)

    def read_field(self, record_id: str, field: str) -> tuple[Any, int]:
        """Scoped read; also the reader the grounding validator uses."""
        self._check("read_field", record_id)
        value, version = self._read_field(record_id, field)
        self.calls.append(
            {"tool": "read_field", "record_id": record_id, "field": field, "outcome": "ok"}
        )
        return value, version

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a model-requested tool call; the result goes back to the model as data."""
        self._check(tool, arguments.get("record_id"))
        if tool != "read_field":
            raise ScopeViolation(f"unknown tool {tool!r}")
        try:
            value, version = self.read_field(arguments["record_id"], arguments["field"])
        except (KeyError, LookupError):
            return {"error": "not_found"}
        return {"value": value, "version": version}
