"""ModelClient seam: LIVE (OpenAI-compatible HTTP) and REPLAY (recordings on disk).

The API key is read from the environment at call time and is never logged or put in errors.
A missing recording is an error; nothing here ever falls back from one client to the other.
"""

import argparse
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx
from vera_domain.specialists import ExecutionMode

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL_ID = "meta/llama-3.3-70b-instruct"  # override with VERA_MODEL_ID
DEFAULT_RECORDINGS = Path("evals/recordings")
KEY_ENV = "NVIDIA_API_KEY"


class ModelError(Exception):
    def __init__(self, reason: str, message: str = "") -> None:
        self.reason = reason
        super().__init__(f"{reason}: {message}" if message else reason)


@dataclass(frozen=True)
class ModelResult:
    content: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    usage: dict[str, Any]
    model_id: str
    mode: ExecutionMode
    provenance: str | None = None  # "authored-reference" for hand-written recordings


class ModelClient(Protocol):
    def complete(
        self,
        *,
        specialist: str,
        prompt_version: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any] | None,
        tools: list[dict[str, Any]],
    ) -> ModelResult: ...


def default_mode() -> ExecutionMode:
    """VERA_EXECUTION_MODE. Unset defaults to replay only in tests (VERA_ENV=test or pytest);
    anywhere else it is an error, so a product path never silently replays recordings."""
    mode = os.environ.get("VERA_EXECUTION_MODE")
    if mode:
        return ExecutionMode(mode)
    if os.environ.get("VERA_ENV") == "test" or "PYTEST_CURRENT_TEST" in os.environ:
        return ExecutionMode.REPLAY
    raise RuntimeError("VERA_EXECUTION_MODE is not set; choose 'live' or 'replay' explicitly")


def make_client(mode: ExecutionMode, case_id: str) -> ModelClient:
    """Product client factory for SpecialistRunner: one client per step, chosen only by mode."""
    if mode is ExecutionMode.LIVE:
        return LiveModelClient()
    return RecordedModelClient(case_id=case_id)


class LiveModelClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model_id: str | None = None,
        timeout: float = 45.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("VERA_BASE_URL")
            or os.environ.get("VERA_MODEL_BASE_URL")  # accepted as an alias of VERA_BASE_URL
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model_id = model_id or os.environ.get("VERA_MODEL_ID") or DEFAULT_MODEL_ID
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def complete(
        self,
        *,
        specialist: str,
        prompt_version: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any] | None,
        tools: list[dict[str, Any]],
    ) -> ModelResult:
        key = os.environ.get(KEY_ENV, "")
        if not key:
            raise ModelError("provider_error", f"{KEY_ENV} is not set; live mode cannot run")
        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": list(messages),
            "temperature": 0,
        }
        if response_schema is not None:
            body["response_format"] = {"type": "json_object"}
            body["messages"] = [
                *messages,
                {
                    "role": "system",
                    "content": "Reply with one JSON object matching this JSON schema: "
                    + json.dumps(response_schema),
                },
            ]
        if tools:
            body["tools"] = tools
        data = self._post(body, key)
        return self._parse(data, strict=response_schema is not None)

    def _post(self, body: dict[str, Any], key: str) -> dict[str, Any]:
        last: ModelError | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                self._sleep(0.5 * 2 ** (attempt - 1))
            try:
                with httpx.Client(timeout=self.timeout, transport=self._transport) as http:
                    resp = http.post(
                        f"{self.base_url}/chat/completions",
                        json=body,
                        headers={"Authorization": f"Bearer {key}"},
                    )
            except httpx.TimeoutException:
                last = ModelError("timeout", f"no response within {self.timeout}s")
                continue
            except httpx.HTTPError as exc:
                last = ModelError("provider_error", f"transport error {type(exc).__name__}")
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last = ModelError("provider_error", f"provider returned HTTP {resp.status_code}")
                continue
            if resp.status_code >= 400:
                raise ModelError("provider_error", f"provider returned HTTP {resp.status_code}")
            try:
                data = resp.json()
            except ValueError:
                raise ModelError("provider_error", "provider returned a non-JSON body") from None
            if not isinstance(data, dict):
                raise ModelError("provider_error", "unexpected provider response")
            return data
        assert last is not None
        raise last

    def _parse(self, data: dict[str, Any], *, strict: bool) -> ModelResult:
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError("provider_error", "response has no choices") from None
        calls: list[dict[str, Any]] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                raise ModelError("schema_invalid", "tool call arguments are not JSON") from None
            calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "arguments": args})
        text = message.get("content") or ""
        content: dict[str, Any] = {}
        if text.strip():
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                content = parsed
            elif strict and not calls:
                raise ModelError("schema_invalid", "model content is not a JSON object")
        elif strict and not calls:
            raise ModelError("schema_invalid", "model returned no content")
        return ModelResult(
            content=content,
            tool_calls=calls,
            usage=dict(data.get("usage") or {}),
            model_id=str(data.get("model") or self.model_id),
            mode=ExecutionMode.LIVE,
        )


def recording_path(root: Path, specialist: str, prompt_version: str, case_id: str, n: int) -> Path:
    name = f"{case_id}.json" if n == 0 else f"{case_id}.{n}.json"
    return root / specialist / prompt_version / name


class RecordedModelClient:
    """Serves `{case_id}.json`, then `{case_id}.1.json`, ... for successive calls of one step."""

    def __init__(self, root: Path | str = DEFAULT_RECORDINGS, *, case_id: str) -> None:
        self.root = Path(root)
        self.case_id = case_id
        self._calls: dict[tuple[str, str], int] = {}

    def complete(
        self,
        *,
        specialist: str,
        prompt_version: str,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any] | None,
        tools: list[dict[str, Any]],
    ) -> ModelResult:
        k = (specialist, prompt_version)
        n = self._calls.get(k, 0)
        self._calls[k] = n + 1
        path = recording_path(self.root, specialist, prompt_version, self.case_id, n)
        if not path.is_file():
            raise ModelError("missing_recording", f"no recording at {path}")
        raw = json.loads(path.read_text())
        return ModelResult(
            content=raw["content"],
            tool_calls=raw.get("tool_calls", []),
            usage=raw.get("usage", {}),
            model_id=raw["model_id"],
            mode=ExecutionMode.REPLAY,
            provenance=raw.get("provenance"),
        )


def record(
    result: ModelResult,
    *,
    root: Path | str,
    specialist: str,
    prompt_version: str,
    case_id: str,
    n: int = 0,
) -> Path:
    path = recording_path(Path(root), specialist, prompt_version, case_id, n)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "model_id": result.model_id,
        "content": result.content,
        "tool_calls": result.tool_calls,
        "usage": result.usage,
    }
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return path


@dataclass
class ProbeResult:
    model_id: str
    json_mode: bool = False
    tool_calls: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.json_mode and self.tool_calls


PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_field",
        "description": "Read one field of a record.",
        "parameters": {
            "type": "object",
            "properties": {"record_id": {"type": "string"}, "field": {"type": "string"}},
            "required": ["record_id", "field"],
        },
    },
}


def probe_model(client: ModelClient) -> ProbeResult:
    """Capability check that pins a model id: JSON output and a tool-call round trip."""
    out = ProbeResult(model_id=getattr(client, "model_id", ""))
    try:
        r = client.complete(
            specialist="probe",
            prompt_version="v0",
            messages=[{"role": "user", "content": 'Reply with {"ok": true}.'}],
            response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            tools=[],
        )
        out.model_id = r.model_id
        out.json_mode = r.content.get("ok") is True
        if not out.json_mode:
            out.errors.append("json mode: reply was not the requested object")
    except ModelError as exc:
        out.errors.append(f"json mode: {exc}")
    try:
        r = client.complete(
            specialist="probe",
            prompt_version="v0",
            messages=[{"role": "user", "content": "Call read_field for record A, field amount."}],
            response_schema=None,
            tools=[PROBE_TOOL],
        )
        out.tool_calls = any(c.get("name") == "read_field" for c in r.tool_calls)
        if not out.tool_calls:
            out.errors.append("tool calls: model did not call the tool")
    except ModelError as exc:
        out.errors.append(f"tool calls: {exc}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m vera_api.model_client")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="check JSON-mode and tool-call support of VERA_MODEL_ID")
    rec = sub.add_parser("record", help="run one LIVE call and write a recording")
    rec.add_argument("--specialist", required=True)
    rec.add_argument("--prompt-version", required=True)
    rec.add_argument("--case-id", required=True)
    rec.add_argument("--n", type=int, default=0, help="call index within the step (retries)")
    rec.add_argument("--request", required=True, help="JSON file: messages, response_schema, tools")
    rec.add_argument("--root", default=str(DEFAULT_RECORDINGS))
    args = p.parse_args(argv)
    client = LiveModelClient()
    if args.cmd == "probe":
        res = probe_model(client)
        print(json.dumps({**res.__dict__, "ok": res.ok}, indent=2))
        return 0 if res.ok else 1
    req = json.loads(Path(args.request).read_text())
    result = client.complete(
        specialist=args.specialist,
        prompt_version=args.prompt_version,
        messages=req["messages"],
        response_schema=req.get("response_schema"),
        tools=req.get("tools", []),
    )
    print(
        record(
            result,
            root=args.root,
            specialist=args.specialist,
            prompt_version=args.prompt_version,
            case_id=args.case_id,
            n=args.n,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
