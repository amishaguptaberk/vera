import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from vera_api.model_client import (
    LiveModelClient,
    ModelError,
    ModelResult,
    RecordedModelClient,
    probe_model,
    record,
)
from vera_domain.specialists import ExecutionMode

KEY = "nvapi-STUB-SECRET-KEY-123"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
MSGS = [{"role": "user", "content": "hi"}]


def chat(content: str = '{"ok": true}', tool_calls: list[dict[str, Any]] | None = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "model": "stub-model",
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7},
    }


def live(handler: Any, **kw: Any) -> LiveModelClient:
    return LiveModelClient(
        base_url="http://stub/v1",
        model_id="stub-model",
        transport=httpx.MockTransport(handler),
        sleep=lambda _s: None,
        **kw,
    )


def call(client: LiveModelClient) -> ModelResult:
    return client.complete(
        specialist="echo-check",
        prompt_version="v1",
        messages=MSGS,
        response_schema=SCHEMA,
        tools=[],
    )


@pytest.fixture(autouse=True)
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", KEY)


def test_live_request_shape_and_result() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=chat())

    result = call(live(handler))
    [req] = seen
    body = json.loads(req.content)
    assert str(req.url) == "http://stub/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert body["model"] == "stub-model"
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0] == MSGS[0]
    assert "tools" not in body
    assert result.content == {"ok": True}
    assert result.usage == {"prompt_tokens": 5, "completion_tokens": 7}
    assert result.model_id == "stub-model"
    assert result.mode is ExecutionMode.LIVE


def test_retries_429_then_succeeds_and_bounds_at_two_retries() -> None:
    codes = iter([429, 503, 200])
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        code = next(codes)
        calls.append(code)
        return httpx.Response(code, json=chat() if code == 200 else {"error": "x"})

    assert call(live(handler)).content == {"ok": True}
    assert calls == [429, 503, 200]

    n = {"c": 0}

    def always_500(req: httpx.Request) -> httpx.Response:
        n["c"] += 1
        return httpx.Response(500, json={})

    with pytest.raises(ModelError) as e:
        call(live(always_500))
    assert e.value.reason == "provider_error"
    assert n["c"] == 3  # 1 call + 2 retries


def test_timeout_is_typed_after_retries() -> None:
    n = {"c": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        n["c"] += 1
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(ModelError) as e:
        call(live(handler))
    assert e.value.reason == "timeout" and n["c"] == 3


def test_client_error_is_not_retried_and_bad_json_is_schema_invalid() -> None:
    n = {"c": 0}

    def h400(req: httpx.Request) -> httpx.Response:
        n["c"] += 1
        return httpx.Response(400, json={"error": "bad"})

    with pytest.raises(ModelError) as e:
        call(live(h400))
    assert e.value.reason == "provider_error" and n["c"] == 1

    with pytest.raises(ModelError) as e2:
        call(live(lambda r: httpx.Response(200, json=chat("not json"))))
    assert e2.value.reason == "schema_invalid"


def test_missing_key_is_a_clear_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY")
    with pytest.raises(ModelError) as e:
        call(live(lambda r: httpx.Response(200, json=chat())))
    assert e.value.reason == "provider_error" and "NVIDIA_API_KEY" in str(e.value)


def test_key_never_appears_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ModelError) as e:
        call(live(lambda r: httpx.Response(500, text=f"echo {KEY}")))
    assert KEY not in str(e.value) and KEY not in repr(e.value)
    call(live(lambda r: httpx.Response(200, json=chat())))
    assert KEY not in caplog.text


def test_recorded_client_replays_numbered_files_and_missing_is_an_error(tmp_path: Path) -> None:
    first = ModelResult(
        content={"ok": True},
        tool_calls=[],
        usage={"total_tokens": 3},
        model_id="m1",
        mode=ExecutionMode.LIVE,
    )
    p0 = record(first, root=tmp_path, specialist="echo-check", prompt_version="v1", case_id="C1")
    p1 = record(
        first, root=tmp_path, specialist="echo-check", prompt_version="v1", case_id="C1", n=1
    )
    assert p0 == tmp_path / "echo-check" / "v1" / "C1.json"
    assert p1 == tmp_path / "echo-check" / "v1" / "C1.1.json"

    c = RecordedModelClient(tmp_path, case_id="C1")
    r = c.complete(
        specialist="echo-check",
        prompt_version="v1",
        messages=MSGS,
        response_schema=SCHEMA,
        tools=[],
    )
    assert r.content == {"ok": True} and r.mode is ExecutionMode.REPLAY and r.model_id == "m1"
    c.complete(
        specialist="echo-check",
        prompt_version="v1",
        messages=MSGS,
        response_schema=SCHEMA,
        tools=[],
    )
    with pytest.raises(ModelError) as e:  # third call: no C1.2.json, never falls back
        c.complete(
            specialist="echo-check",
            prompt_version="v1",
            messages=MSGS,
            response_schema=SCHEMA,
            tools=[],
        )
    assert e.value.reason == "missing_recording"
    with pytest.raises(ModelError) as e2:
        RecordedModelClient(tmp_path, case_id="NOPE").complete(
            specialist="echo-check",
            prompt_version="v1",
            messages=MSGS,
            response_schema=SCHEMA,
            tools=[],
        )
    assert e2.value.reason == "missing_recording"


def test_probe_reports_json_and_tool_support() -> None:
    def good(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if "tools" in body:
            tc = [
                {
                    "id": "1",
                    "type": "function",
                    "function": {"name": "read_field", "arguments": '{"record_id": "A"}'},
                }
            ]
            return httpx.Response(200, json=chat("", tc))
        return httpx.Response(200, json=chat())

    p = probe_model(live(good))
    assert p.json_mode and p.tool_calls and p.ok and p.model_id == "stub-model"

    weak = probe_model(live(lambda r: httpx.Response(200, json=chat("plain words"))))
    assert not weak.json_mode and not weak.tool_calls and not weak.ok and weak.errors
