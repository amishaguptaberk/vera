class CommandError(Exception):
    """Typed gateway failure; the API renders it as top-level JSON."""

    def __init__(
        self,
        code: str,
        http_status: int,
        message: str,
        blocked_reason: str | None = None,
        case_version: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message
        self.blocked_reason = blocked_reason
        self.case_version = case_version

    def body(self) -> dict[str, object]:
        out: dict[str, object] = {"code": self.code, "message": self.message}
        if self.blocked_reason is not None:
            out["blocked_reason"] = self.blocked_reason
        if self.case_version is not None:
            out["case_version"] = self.case_version
        return out
