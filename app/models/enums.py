"""The persisted status and code values of spec section 6.

They are stored as `VARCHAR` with a named `CHECK` constraint, never as a native
PostgreSQL enum, so adding a value is an additive migration that drops and
recreates the `CHECK` by name. `openapi.yaml` spells the same values; a unit
test keeps the two in step. `Recovered` is a UI label, not a status.
"""

IMPORT_STATUSES = ("PROCESSING", "COMPLETED", "FAILED")
FAILURE_CODES = ("VALIDATION_ERROR", "TRANSIENT_STORAGE_TIMEOUT", "INTERNAL_ERROR")
ATTEMPT_STATUSES = ("RUNNING", "SUCCEEDED", "FAILED")
ALERT_STATUSES = ("OPEN", "IN_PROGRESS", "RESOLVED", "NEEDS_ATTENTION")
AGENT_ACTIONS = ("RUN_STARTED", "TOOL_CALL", "DECISION", "RUN_FINISHED", "ERROR")


def check_in(column: str, values: tuple[str, ...]) -> str:
    """SQL for a `CHECK (<column> IN (...))`. `NULL` passes, as SQL `CHECK` allows."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"
