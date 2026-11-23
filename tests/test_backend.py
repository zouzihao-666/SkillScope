import json
import sys

import httpx
import pytest
from openai import OpenAI

from skillscope.backend import DeepSeekBackend, RunError
from skillscope.settings import Settings, load_settings


def completion(arguments=None, finish="tool_calls", name="submit_implement"):
    return {
        "id": "test-response",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model-version",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call1",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments
                                or json.dumps(
                                    {"code": "def clamp(value, lower, upper):\n    return value\n"}
                                ),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def backend_with_handler(handler):
    backend = DeepSeekBackend(Settings(api_key="test-secret"), 1024, 10)
    backend.client.close()
    backend.client = OpenAI(
        api_key="test-secret",
        base_url="https://api.deepseek.com",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return backend


def test_request_fixes_non_thinking_tool_and_records_usage():
    requests, events = [], []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=completion())

    backend = backend_with_handler(handler)
    try:
        code = backend.complete(
            "deepseek-flash", "implement", [{"role": "user", "content": "fix"}], events.append
        )
        assert "def clamp" in code
        assert len(requests) == 1
        assert requests[0]["thinking"] == {"type": "disabled"}
        assert requests[0]["max_tokens"] == 1024
        assert requests[0]["tool_choice"]["function"]["name"] == "submit_implement"
        assert events[-1]["response"]["usage"]["total_tokens"] == 30
        assert "test-secret" not in json.dumps(events)
        assert "test-secret" not in json.dumps(backend.redact({"nested": ["test-secret"]}))
    finally:
        backend.close()


@pytest.mark.parametrize("status", [401, 402, 429, 500])
def test_provider_errors_do_not_retry_or_expose_response_body(status):
    requests, events = [], []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "test-secret", "type": "failure"}})

    backend = backend_with_handler(handler)
    try:
        with pytest.raises(RunError) as error:
            backend.complete("deepseek-flash", "implement", [], events.append)
        assert error.value.status == "api_error"
        assert len(requests) == 1
        assert "test-secret" not in str(error.value) + json.dumps(events)
    finally:
        backend.close()


@pytest.mark.parametrize(
    "payload",
    [
        completion(finish="length"),
        completion(name="run_shell"),
        completion(arguments="not json"),
        completion(arguments='{"code": 42}'),
        completion(arguments='{"code": ""}'),
        completion(arguments='{"code": "ok", "other": true}'),
    ],
)
def test_invalid_outputs_are_recorded_but_never_executed(payload):
    events = []
    backend = backend_with_handler(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(RunError) as error:
            backend.complete("deepseek-flash", "implement", [], events.append)
        assert error.value.status == "invalid_output"
        assert events[-1]["type"] == "response"  # Preserve token usage even for invalid outputs.
    finally:
        backend.close()


def test_settings_require_key_and_reject_unapproved_credential_destination(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("SKILLSCOPE_BASE_URL", raising=False)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing DEEPSEEK_API_KEY"):
        load_settings(env)
    env.write_text(
        "DEEPSEEK_API_KEY=test-secret\nSKILLSCOPE_BASE_URL=https://example.com\n", encoding="utf-8"
    )
    with pytest.raises(ValueError) as error:
        load_settings(env)
    assert "test-secret" not in str(error.value)


def test_custom_env_file_supplies_docker_path_without_using_default_file(tmp_path, monkeypatch):
    for key in (
        "DEEPSEEK_API_KEY",
        "SKILLSCOPE_DOCKER",
        "SKILLSCOPE_BASE_URL",
        "SKILLSCOPE_THINKING",
    ):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / "custom.env"
    env.write_text(
        "DEEPSEEK_API_KEY=test-secret\nSKILLSCOPE_DOCKER=" + sys.executable + "\n", encoding="utf-8"
    )
    settings = load_settings(env)
    assert settings.docker == sys.executable
    assert "test-secret" not in repr(settings)
