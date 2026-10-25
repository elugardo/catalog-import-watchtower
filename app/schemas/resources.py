"""Response models for the resources of `openapi.yaml` -> `components/schemas`.

Each class mirrors one YAML schema; `tests/unit/test_contract_schemas.py`
asserts that their property names match, so the two cannot drift silently.
There is no `csv_bytes`, no `normalized_*` field and no price in dollars here.
"""

from typing import Any, Literal

from pydantic import Field, StrictInt

from app.schemas.common import ApiModel, UtcDateTime, ValidationErrorOut

# The persisted values of spec section 6 (`app.models.enums` holds the same tuples).
ImportStatus = Literal["PROCESSING", "COMPLETED", "FAILED"]
FailureCode = Literal["VALIDATION_ERROR", "TRANSIENT_STORAGE_TIMEOUT", "INTERNAL_ERROR"]
AttemptStatus = Literal["RUNNING", "SUCCEEDED", "FAILED"]
AlertStatus = Literal["OPEN", "IN_PROGRESS", "RESOLVED", "NEEDS_ATTENTION"]
AgentActionKind = Literal["RUN_STARTED", "TOOL_CALL", "DECISION", "RUN_FINISHED", "ERROR"]


class VendorOut(ApiModel):
    id: int
    display_name: str


class ProductOut(ApiModel):
    id: int
    vendor_id: int
    sku: str
    name: str
    # Strict: integer cents, never a float (AGENTS.md -> Rules).
    price_cents: StrictInt = Field(ge=0)
    quantity: StrictInt = Field(ge=0)
    updated_at: UtcDateTime


class AttemptOut(ApiModel):
    number: int = Field(ge=1)
    status: AttemptStatus
    error_code: FailureCode | None
    trace_id: str | None
    started_at: UtcDateTime
    finished_at: UtcDateTime | None


class AlertOut(ApiModel):
    id: int
    status: AlertStatus
    reason: str
    claimed_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class AlertListItemOut(AlertOut):
    """An alert with its import summary (`GET /api/alerts`)."""

    import_id: int
    import_status: ImportStatus
    failure_code: FailureCode | None
    vendor_display_name: str
    filename: str


class AgentActionOut(ApiModel):
    id: int
    action: AgentActionKind
    tool_name: str | None
    reason_summary: str | None
    result: dict[str, Any] | None
    created_at: UtcDateTime


class ImportOut(ApiModel):
    """One import as listed in `GET /api/imports`."""

    id: int
    vendor: VendorOut
    filename: str
    sha256: str
    row_count: int = Field(ge=0)
    # Null unless COMPLETED (spec section 4 F2).
    product_count: int | None = Field(ge=0)
    status: ImportStatus
    failure_code: FailureCode | None
    validation_errors: list[ValidationErrorOut] = Field(max_length=20)
    validation_error_count: int = Field(ge=0)
    inject_transient_failure: bool
    attempt_count: int = Field(ge=0)
    # Derived, never stored: `status == COMPLETED and attempt_count > 1`.
    recovered: bool
    created_at: UtcDateTime
    # Set only when COMPLETED.
    completed_at: UtcDateTime | None


class ImportDetailOut(ImportOut):
    """`GET /api/imports/{id}` and the 201 of `POST /api/imports`."""

    attempts: list[AttemptOut]
    alert: AlertOut | None
    agent_actions: list[AgentActionOut]
