"""One LLM conversation for one claimed alert (`_docs/team/oncall-agent.md`).

Provider: Anthropic, through the official `anthropic` SDK with tool calling.
The provider client is the only thing a test replaces (`tests/oncall/`): it is
any object with `messages.create(**kwargs)` returning an Anthropic `Message`.
The loop, the tool dispatch and the six tools are the same in tests and in
the running worker.

What the model receives: the system prompt (`prompt.py`), a first message with
the two claimed ids, the six tool definitions, and the tool results, which are
the redacted dicts of `app/services/agent_tools.py` serialised as JSON, or a
fixed-text error from this module. Nothing is logged of the prompt, the
request, the response or the tool results.

**The run is bound to its claim.** Every tool call must name the claimed
`alert_id` or that alert's `import_id`. Any other id, an unknown tool, an
argument that is not JSON, a missing or extra argument, or an id that is not
an integer is refused here, before any tool function runs: the model gets a
fixed-text tool error, the call counts toward `AGENT_MAX_TOOL_CALLS`, and a
`TOOL_CALL` row on the claimed alert records the refusal.

**Audit rows** (`agent_actions`, all on the claimed alert): `RUN_STARTED`
(provider and model), the tools' own `TOOL_CALL` rows, `DECISION` (the reason
the model stated, when its `resolve_alert` or `mark_needs_attention` was
`DONE`), `ERROR` (an exception in the loop: its type only) and
`RUN_FINISHED` (outcome, tool-call count, duration).

**Bounds.** At most `max_tool_calls` model tool calls (the one after that is
not executed) and `timeout_seconds` of wall time: each provider call gets only
the time that is left, and a tool call already running is not interrupted. A
run that hits either bound, ends without a decision, or raises is closed by
the worker with `mark_needs_attention`, so no alert is left `IN_PROGRESS`.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app import telemetry
from app.db import get_sessionmaker
from app.models import AgentAction
from app.oncall import prompt
from app.services import agent_tools, alerts

log = logging.getLogger("app.oncall.llm")

PROVIDER = "anthropic"
MAX_TOKENS = 4096
MAX_DECISION_LENGTH = alerts.MAX_REASON_LENGTH

RESOLVED = "RESOLVED"
NEEDS_ATTENTION = "NEEDS_ATTENTION"

REASON_LIMITS = "agent run exceeded limits"
REASON_NO_DECISION = "agent ended without a decision"

# Each tool's arguments, by name and type (the CLI's list, `app/oncall/cli.py`).
ARGUMENTS: dict[str, dict[str, type]] = {
    "get_import_incident": {"alert_id": int},
    "get_import_attempts": {"import_id": int},
    "get_import_diagnostics": {"import_id": int},
    "retry_failed_import": {"import_id": int},
    "mark_needs_attention": {"alert_id": int, "reason": str},
    "resolve_alert": {"alert_id": int},
}

_DESCRIPTIONS = {
    "get_import_incident": "The redacted incident of the claimed alert: statuses, failure "
    "code, attempts, counts and timestamps. Read-only. Call it first.",
    "get_import_attempts": "The attempts of the claimed import: number, status, error code, "
    "trace id, timings. Read-only.",
    "get_import_diagnostics": "Log and trace query references for the claimed import, plus "
    "its counts. Read-only.",
    "retry_failed_import": "Re-process the saved file of the claimed import as attempt 2. "
    "Allowed only for a FAILED import with failure code TRANSIENT_STORAGE_TIMEOUT and "
    "exactly one attempt; otherwise refused as a no-op.",
    "mark_needs_attention": "Escalate the claimed alert to a human (IN_PROGRESS -> "
    "NEEDS_ATTENTION) with a short, content-free reason of at most 200 characters.",
    "resolve_alert": "Resolve the claimed alert. Allowed only when the import is COMPLETED.",
}

_SCHEMA_PROPERTIES = {
    "alert_id": {"type": "integer", "description": "The claimed alert's id."},
    "import_id": {"type": "integer", "description": "The claimed alert's import id."},
    "reason": {"type": "string", "description": "Short, content-free reason."},
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": name,
        "description": _DESCRIPTIONS[name],
        "input_schema": {
            "type": "object",
            "properties": {arg: _SCHEMA_PROPERTIES[arg] for arg in arguments},
            "required": list(arguments),
            "additionalProperties": False,
        },
    }
    for name, arguments in ARGUMENTS.items()
]
assert tuple(ARGUMENTS) == agent_tools.TOOL_NAMES


@dataclass(frozen=True)
class Limits:
    max_tool_calls: int = 8
    timeout_seconds: float = 120.0


@dataclass
class RunSummary:
    """What a run ended with (also written to `RUN_FINISHED`)."""

    outcome: str
    tool_calls: int
    duration_ms: int
    closed_by: str  # "model" or "worker"
    close_reason: str | None = None
    close_refused_reason: str | None = None


def make_client() -> Any:
    """The real provider client. The SDK reads `ANTHROPIC_API_KEY` itself; this code never does.

    `max_retries=0`: a retry would let one provider call outlive the run's time budget.
    """
    import anthropic

    return anthropic.Anthropic(max_retries=0)


# ---- audit rows written by the worker -----------------------------------------------------


def _write_action(
    alert_id: int,
    action: str,
    *,
    tool_name: str | None = None,
    reason_summary: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    with get_sessionmaker()() as session, session.begin():
        session.add(
            AgentAction(
                alert_id=alert_id,
                action=action,
                tool_name=tool_name,
                reason_summary=reason_summary,
                result=result,
            )
        )


# ---- one tool call ------------------------------------------------------------------------


@dataclass
class _Call:
    content: str
    is_error: bool
    outcome: str = ""  # the tool's result status: DONE, REFUSED or NOT_FOUND
    decision: str | None = None  # RESOLVED / NEEDS_ATTENTION when a deciding call was DONE
    reason: str | None = None  # the mark_needs_attention reason, when it decided


class _Refusal(Exception):
    """A tool call refused by the worker; `problem` is fixed text, never a model value."""

    def __init__(self, problem: str) -> None:
        super().__init__(problem)
        self.problem = problem


def _arguments(name: str, raw: Any, alert_id: int, import_id: int) -> dict[str, Any]:
    """The checked arguments of one tool call, or `_Refusal`."""
    if name not in ARGUMENTS:
        raise _Refusal("unknown tool")
    if isinstance(raw, str | bytes):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise _Refusal("arguments are not valid JSON") from None
    if not isinstance(raw, dict):
        raise _Refusal("arguments must be a JSON object")
    expected = ARGUMENTS[name]
    if set(raw) != set(expected):
        raise _Refusal(f"{name} takes exactly: {', '.join(expected)}")
    for key, kind in expected.items():
        value = raw[key]
        if kind is int and (not isinstance(value, int) or isinstance(value, bool)):
            raise _Refusal(f"{key} must be an integer")
        if kind is str and not isinstance(value, str):
            raise _Refusal(f"{key} must be a string")
    if raw.get("alert_id", alert_id) != alert_id or raw.get("import_id", import_id) != import_id:
        raise _Refusal(f"this run may act only on alert {alert_id} and its import {import_id}")
    return dict(raw)


def _tool_span(name: str, alert_id: int, import_id: int) -> Any:
    """One span per tool call, named after the tool; ids only, never an argument or a reason."""
    span_name = name if name in ARGUMENTS else telemetry.SPAN_UNKNOWN_TOOL
    return telemetry.span(span_name, telemetry.ids(alert_id=alert_id, import_id=import_id))


def _tool_finished(span: Any, name: str, outcome: str, alert_id: int, import_id: int) -> None:
    if span.is_recording():
        span.set_attribute(telemetry.ATTR_TOOL_OUTCOME, outcome)
    log.info(
        "oncall-agent: tool %s on alert %s: %s",
        name if name in ARGUMENTS else telemetry.SPAN_UNKNOWN_TOOL,
        alert_id,
        outcome,
        extra=telemetry.log_ids(alert_id=alert_id, import_id=import_id),
    )


def _dispatch(name: str, raw: Any, alert_id: int, import_id: int) -> _Call:
    with _tool_span(name, alert_id, import_id) as span:
        call = _dispatch_call(name, raw, alert_id, import_id)
        _tool_finished(span, name, call.outcome, alert_id, import_id)
    return call


def _dispatch_call(name: str, raw: Any, alert_id: int, import_id: int) -> _Call:
    try:
        arguments = _arguments(name, raw, alert_id, import_id)
    except _Refusal as refusal:
        _write_action(
            alert_id,
            "TOOL_CALL",
            tool_name=name if name in ARGUMENTS else None,
            reason_summary=f"refused by the worker: {refusal.problem}",
            result={"outcome": agent_tools.REFUSED, "alert_id": alert_id, "import_id": import_id},
        )
        return _Call(
            json.dumps({"error": f"refused: {refusal.problem}"}),
            is_error=True,
            outcome=agent_tools.REFUSED,
        )

    result = agent_tools.TOOLS[name](**arguments)
    call = _Call(json.dumps(result), is_error=False, outcome=str(result.get("outcome")))
    if result.get("outcome") == agent_tools.DONE:
        if name == "resolve_alert":
            call.decision = RESOLVED
        elif name == "mark_needs_attention":
            call.decision = NEEDS_ATTENTION
            call.reason = arguments["reason"]
    return call


# ---- the conversation ---------------------------------------------------------------------


def _block_param(block: Any) -> dict[str, Any]:
    """An assistant content block as a request parameter (sent back unchanged in kind)."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        tool_input = block.input if isinstance(block.input, dict) else {}
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": tool_input}
    return block.model_dump(mode="json", exclude_none=True)  # thinking blocks and the like


def _decision_text(response: Any, call: _Call) -> str:
    if call.reason is not None:
        stated = call.reason
    else:
        stated = " ".join(b.text for b in response.content if b.type == "text")
    stated = " ".join(stated.split())[:MAX_DECISION_LENGTH].rstrip()
    return stated or ("import COMPLETED; alert resolved" if call.decision == RESOLVED else "")


def _is_timeout(exc: BaseException) -> bool:
    try:
        import anthropic
    except ImportError:  # pragma: no cover - the SDK is a dependency
        return False
    return isinstance(exc, anthropic.APITimeoutError)


def run_alert(
    client: Any,
    *,
    model: str,
    alert_id: int,
    import_id: int,
    limits: Limits,
    clock: Callable[[], float] = time.monotonic,
) -> RunSummary:
    """Run one conversation on a claimed (`IN_PROGRESS`) alert and close it. Never raises
    for a provider or tool error; a database outage can still raise from the audit writes.

    The run is its own trace: a root `catalog.agent.run` span with the two ids
    and, at the end, the run's outcome and tool-call count; each tool call is a
    child span (`_dispatch`), and a retry's attempt 2 a child of its tool span.
    Nothing of the prompt, the replies or the model's reason text goes on a span.
    """
    with telemetry.span(
        telemetry.SPAN_AGENT_RUN,
        telemetry.ids(alert_id=alert_id, import_id=import_id),
        root=True,
    ) as span:
        summary = _run_alert(
            client, model=model, alert_id=alert_id, import_id=import_id, limits=limits, clock=clock
        )
        if span.is_recording():
            span.set_attribute(telemetry.ATTR_AGENT_OUTCOME, summary.outcome)
            span.set_attribute(telemetry.ATTR_AGENT_TOOL_CALLS, summary.tool_calls)
    return summary


def _run_alert(
    client: Any,
    *,
    model: str,
    alert_id: int,
    import_id: int,
    limits: Limits,
    clock: Callable[[], float],
) -> RunSummary:
    started = clock()
    deadline = started + limits.timeout_seconds
    ids = telemetry.log_ids(alert_id=alert_id, import_id=import_id)
    _write_action(
        alert_id,
        "RUN_STARTED",
        reason_summary=f"provider {PROVIDER}, model {model}",
        result={"provider": PROVIDER, "model": model},
    )
    log.info("oncall-agent: run on alert %s started", alert_id, extra=ids)

    calls = 0
    decision: str | None = None
    close_reason: str | None = None
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": prompt.first_message(alert_id, import_id)}
    ]
    system = prompt.system_prompt(limits.max_tool_calls, limits.timeout_seconds)
    try:
        while decision is None and close_reason is None:
            remaining = deadline - clock()
            if remaining <= 0:
                close_reason = REASON_LIMITS
                break
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=MAX_TOKENS,
                    system=system,
                    tools=TOOL_DEFINITIONS,
                    messages=messages,
                    timeout=remaining,
                )
            except Exception as exc:
                if _is_timeout(exc):  # the call was given only the time that was left
                    close_reason = REASON_LIMITS
                    break
                raise

            messages.append(
                {"role": "assistant", "content": [_block_param(b) for b in response.content]}
            )
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                close_reason = REASON_NO_DECISION
                break

            results: list[dict[str, Any]] = []
            for block in tool_uses:
                if calls >= limits.max_tool_calls or clock() >= deadline:
                    close_reason = REASON_LIMITS
                    break
                calls += 1
                call = _dispatch(block.name, block.input, alert_id, import_id)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": call.content,
                        "is_error": call.is_error,
                    }
                )
                if call.decision is not None:
                    decision = call.decision
                    _write_action(
                        alert_id,
                        "DECISION",
                        tool_name=block.name,
                        reason_summary=_decision_text(response, call),
                        result={"outcome": decision},
                    )
                    break
            messages.append({"role": "user", "content": results})
    except Exception as exc:  # noqa: BLE001 - recorded by type only
        error_type = type(exc).__name__
        log.warning("oncall-agent: run on alert %s raised %s", alert_id, error_type, extra=ids)
        _write_action(
            alert_id, "ERROR", reason_summary=error_type, result={"error_type": error_type}
        )
        close_reason = f"agent run failed ({error_type})"

    summary = _close(alert_id, import_id, decision, close_reason, calls, started, clock)
    log.info(
        "oncall-agent: run on alert %s finished: %s after %s tool calls (closed by %s)",
        alert_id,
        summary.outcome,
        summary.tool_calls,
        summary.closed_by,
        extra=ids,
    )
    return summary


def _close(
    alert_id: int,
    import_id: int,
    decision: str | None,
    close_reason: str | None,
    calls: int,
    started: float,
    clock: Callable[[], float],
) -> RunSummary:
    """Write `RUN_FINISHED`; first escalate the alert when the model did not decide."""
    if decision is not None:
        summary = RunSummary(decision, calls, 0, closed_by="model")
    else:
        reason = close_reason or REASON_NO_DECISION
        with _tool_span("mark_needs_attention", alert_id, import_id) as span:
            result = agent_tools.mark_needs_attention(alert_id, reason)
            _tool_finished(span, "mark_needs_attention", result["outcome"], alert_id, import_id)
        if result["outcome"] == agent_tools.DONE:
            summary = RunSummary(NEEDS_ATTENTION, calls, 0, "worker", close_reason=reason)
        else:  # another worker reset or acted on the alert: record it, do not raise
            summary = RunSummary(
                result.get("alert_status") or result["outcome"],
                calls,
                0,
                "worker",
                close_reason=reason,
                close_refused_reason=result.get("refused_reason"),
            )
    summary.duration_ms = int((clock() - started) * 1000)
    finished: dict[str, Any] = {
        "outcome": summary.outcome,
        "tool_calls": summary.tool_calls,
        "duration_ms": summary.duration_ms,
        "closed_by": summary.closed_by,
    }
    if summary.close_refused_reason is not None:
        finished["close_refused_reason"] = summary.close_refused_reason
    _write_action(alert_id, "RUN_FINISHED", reason_summary=summary.close_reason, result=finished)
    return summary
