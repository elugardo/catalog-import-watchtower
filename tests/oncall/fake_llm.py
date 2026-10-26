"""A fake Anthropic client: scripted responses at the provider-client boundary, no network.

It replaces only `anthropic.Anthropic` (an object with `messages.create`). It
returns real SDK `Message` objects, so the worker's loop, dispatch and tools
run exactly as with the real provider. Every request is recorded (`requests`)
so a test can check what reached the "provider".

A script is a list of steps. A step is a `Message`, or a callable that takes
the request kwargs and returns one (to stall, raise, or read earlier tool
results). Once the script is exhausted the fake answers with plain text,
which the worker treats as "ended without a decision".
"""

from __future__ import annotations

import copy
import itertools
import json
import time
from collections.abc import Callable, Iterable
from typing import Any

import anthropic
import httpx2
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

_ids = itertools.count(1)

Step = Message | Callable[[dict[str, Any]], Message]


def _message(content: list[Any], stop_reason: str) -> Message:
    return Message.model_construct(
        id=f"msg_fake_{next(_ids)}",
        type="message",
        role="assistant",
        model="fake-model",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def tool_use(name: str, raw_input: Any) -> ToolUseBlock:
    """A tool_use block; `raw_input` may be anything (malformed cases bypass validation)."""
    return ToolUseBlock.model_construct(
        type="tool_use", id=f"toolu_fake_{next(_ids)}", name=name, input=raw_input
    )


def call(name: str, text: str | None = None, **arguments: Any) -> Message:
    """One well-formed tool call, optionally preceded by text."""
    content: list[Any] = [TextBlock(type="text", text=text)] if text else []
    return _message([*content, tool_use(name, arguments)], "tool_use")


def calls(*blocks: ToolUseBlock) -> Message:
    """Several tool calls in one response."""
    return _message(list(blocks), "tool_use")


def raw(name: str, raw_input: Any) -> Message:
    """One tool call with an arbitrary (possibly malformed) input."""
    return _message([tool_use(name, raw_input)], "tool_use")


def text(value: str) -> Message:
    return _message([TextBlock(type="text", text=value)], "end_turn")


def stall_then_timeout(request: dict[str, Any]) -> Message:
    """Behaves like the SDK when the provider does not answer within `timeout`."""
    time.sleep(request["timeout"])
    raise anthropic.APITimeoutError(request=httpx2.Request("POST", "https://fake.invalid/v1"))


def connection_error(request: dict[str, Any]) -> Message:
    raise anthropic.APIConnectionError(
        message="fake network failure",
        request=httpx2.Request("POST", "https://fake.invalid/v1"),
    )


class _Messages:
    def __init__(self, script: Iterable[Step]) -> None:
        self._script = iter(script)
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Message:
        self.requests.append(copy.deepcopy(kwargs))
        step = next(self._script, None)
        if step is None:
            return text("I have nothing more to do.")
        return step(kwargs) if callable(step) and not isinstance(step, Message) else step


class FakeAnthropic:
    def __init__(self, script: Iterable[Step]) -> None:
        self.messages = _Messages(script)

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.messages.requests

    def sent(self) -> str:
        """Everything sent to the provider, serialised."""
        return json.dumps(self.requests, default=str)

    def tool_results(self) -> list[dict[str, Any]]:
        """Every tool_result block sent back to the model, in order (deduplicated by id)."""
        seen: dict[str, dict[str, Any]] = {}
        for request in self.requests:
            for message in request["messages"]:
                if message["role"] != "user" or isinstance(message["content"], str):
                    continue
                for block in message["content"]:
                    if block.get("type") == "tool_result":
                        seen.setdefault(block["tool_use_id"], block)
        return list(seen.values())


def tool_results_of(request: dict[str, Any]) -> list[dict[str, Any]]:
    """Every tool_result block of one request, in order."""
    return [
        block
        for message in request["messages"]
        if message["role"] == "user" and not isinstance(message["content"], str)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]


def last_result(request: dict[str, Any]) -> dict[str, Any]:
    """The last tool result the model received in this request, parsed."""
    blocks = request["messages"][-1]["content"]
    return json.loads(blocks[-1]["content"])


def forever(step: Step) -> Iterable[Step]:
    """A model that never stops calling."""
    return itertools.repeat(step)
