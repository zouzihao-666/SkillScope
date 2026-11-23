"""Bounded DeepSeek calls with structured submissions and redacted diagnostics."""

import json
import time

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from skillscope.settings import Settings


class RunError(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def tool_schema(stage: str) -> dict:
    field = "code" if stage == "implement" else "summary"
    return {
        "type": "function",
        "function": {
            "name": f"submit_{stage}",
            "description": "Submit the complete Python module"
            if field == "code"
            else "Submit a concise plain-text analysis of the current phase",
            "parameters": {
                "type": "object",
                "properties": {field: {"type": "string"}},
                "required": [field],
                "additionalProperties": False,
            },
        },
    }


class DeepSeekBackend:
    def __init__(self, settings: Settings, max_tokens: int, timeout: float):
        self.secret = settings.api_key.get_secret_value()
        self.max_tokens = max_tokens
        self.client = OpenAI(
            api_key=self.secret, base_url=settings.base_url, max_retries=0, timeout=timeout
        )

    def close(self) -> None:
        self.client.close()

    def redact(self, value: object) -> object:
        # Only JSON data, not exception reprs or HTTP headers, enter traces.
        text = json.dumps(value, ensure_ascii=False).replace(self.secret, "[REDACTED]")
        return json.loads(text)

    def complete(self, model: str, stage: str, messages: list, record) -> str:
        tool = tool_schema(stage)
        if (
            len(json.dumps({"messages": messages, "tool": tool}, ensure_ascii=False).encode())
            > 65536
        ):
            raise RunError("budget_exhausted", "Request input exceeds 64 KiB limit")
        started = time.monotonic()
        record(
            {
                "type": "request",
                "stage": stage,
                "model": model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": 0,
                "thinking": "disabled",
                "tool": tool,
                "max_retries": 0,
            }
        )
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool["function"]["name"]}},
                temperature=0,
                max_tokens=self.max_tokens,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except APIStatusError as error:
            record({"type": "api_error", "stage": stage, "http_status": error.status_code})
            raise RunError(
                "api_error", f"DeepSeek HTTP {error.status_code}; see local trace"
            ) from None
        except (APIConnectionError, APITimeoutError):
            record({"type": "api_error", "stage": stage, "http_status": None})
            raise RunError("api_error", "DeepSeek connection failed or timed out") from None
        record(
            {
                "type": "response",
                "stage": stage,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "response": response.model_dump(mode="json"),
            }
        )
        if len(response.choices) != 1:
            raise RunError("invalid_output", "Expected exactly one model choice")
        choice = response.choices[0]
        calls = choice.message.tool_calls or []
        if choice.finish_reason != "tool_calls" or len(calls) != 1:
            raise RunError("invalid_output", "Expected one completed structured tool submission")
        call = calls[0]
        if call.type != "function" or call.function.name != tool["function"]["name"]:
            raise RunError("invalid_output", "Unexpected tool submission")
        field = "code" if stage == "implement" else "summary"
        try:
            data = json.loads(call.function.arguments)
        except ValueError:
            raise RunError("invalid_output", "Tool arguments are not valid JSON") from None
        if not isinstance(data, dict) or set(data) != {field}:
            raise RunError("invalid_output", "Tool arguments do not match the submission schema")
        value = data[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 50000:
            raise RunError("invalid_output", "Tool submission is empty, too long, or not text")
        return value
