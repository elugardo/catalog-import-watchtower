"""`python -m app.oncall tools <tool> [args]`: run one agent tool by hand.

The maintenance CLI of `_docs/architecture.md` -> *On-call worker loop*,
step 4. It calls the same functions as the worker (`app/services/agent_tools.py`),
so the guards and the `TOOL_CALL` audit rows are the same. It works with the
agent disabled and no LLM key (it reads neither), never runs the startup
sweep, and returns after the one call. It offers no claim: a human cannot
take an alert `IN_PROGRESS` through it.

Output: the tool's result as one JSON object on stdout; logs on stderr.
Exit codes: 0 `DONE`, 1 `REFUSED`, 2 usage error (nothing touched),
3 `NOT_FOUND`, 4 unexpected error (one stderr line naming only the exception
type: no traceback, no message, no DSN).
"""

import json
import logging
import re
import sys
from typing import Any, TextIO

EXIT_DONE = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_NOT_FOUND = 3
EXIT_ERROR = 4

# Each tool's arguments, in order. No tool takes an attempt number.
ARGUMENTS: dict[str, tuple[str, ...]] = {
    "get_import_incident": ("alert_id",),
    "get_import_attempts": ("import_id",),
    "get_import_diagnostics": ("import_id",),
    "retry_failed_import": ("import_id",),
    "mark_needs_attention": ("alert_id", "reason"),
    "resolve_alert": ("alert_id",),
}

_INTEGER_RE = re.compile(r"-?[0-9]+")

USAGE = "usage: python -m app.oncall tools <tool> [args]\ntools:\n" + "\n".join(
    "  " + " ".join([name, *(f'"<{a}>"' if a == "reason" else f"<{a}>" for a in args)])
    for name, args in ARGUMENTS.items()
)

log = logging.getLogger("app.oncall.cli")


def _usage(stderr: TextIO, problem: str) -> int:
    print(f"error: {problem}", file=stderr)
    print(USAGE, file=stderr)
    return EXIT_USAGE


def _parse(argv: list[str]) -> tuple[str, list[Any]] | str:
    """The tool name and its typed arguments, or the usage problem (never echoes a value)."""
    if not argv:
        return "no tool given"
    tool, values = argv[0], argv[1:]
    if tool not in ARGUMENTS:
        return "unknown tool"
    names = ARGUMENTS[tool]
    if len(values) != len(names):
        return f"{tool} takes {len(names)} argument(s), got {len(values)}"
    parsed: list[Any] = []
    for name, value in zip(names, values, strict=True):
        if name == "reason":
            parsed.append(value)
            continue
        if not _INTEGER_RE.fullmatch(value):
            return f"{name} must be an integer"
        try:
            parsed.append(int(value))
        except ValueError:  # more digits than int() accepts: no id that long exists
            return f"{name} must be an integer"
    return tool, parsed


def run(argv: list[str], stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parsed = _parse(argv)
    if isinstance(parsed, str):
        return _usage(stderr, parsed)
    tool, args = parsed

    configured = False
    try:
        # Imported here, after the usage check: a usage error touches nothing.
        # Inside the try, so an import-time failure exits 4 with the type only,
        # never 1 (REFUSED) with a traceback.
        from app import telemetry

        # JSON log lines on stderr; stdout stays the one result object. The
        # telemetry is that of the container the command runs in, and a retry
        # here is the root of its own trace (no tool span: no agent run).
        telemetry.setup_logging(stderr)
        configured = telemetry.configure("ciw-oncall-agent")
        from app.services import agent_tools

        result = agent_tools.TOOLS[tool](*args)
    except Exception as exc:  # noqa: BLE001 - one line, the type only
        print(f"error: {type(exc).__name__}", file=stderr)
        return EXIT_ERROR
    finally:
        if configured:
            telemetry.shutdown()  # flush before the process exits
    print(json.dumps(result), file=stdout)
    return {
        agent_tools.DONE: EXIT_DONE,
        agent_tools.REFUSED: EXIT_REFUSED,
        agent_tools.NOT_FOUND: EXIT_NOT_FOUND,
    }[result["outcome"]]
