"""`imports` and `import_attempts` (spec section 6).

There is no `attempt_count` or `recovered` column: both are derived from the
attempts (`_docs/api.md`).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import ATTEMPT_STATUSES, FAILURE_CODES, IMPORT_STATUSES, check_in


class Import(Base):
    __tablename__ = "imports"
    __table_args__ = (
        CheckConstraint(check_in("status", IMPORT_STATUSES), name="status"),
        CheckConstraint(check_in("failure_code", FAILURE_CODES), name="failure_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vendor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("vendors.id"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    # The raw upload (at most 256 KiB, checked before insert), kept for the retry.
    csv_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Hex SHA-256 of `csv_bytes`.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Set only when the import is COMPLETED (spec section 4 F2).
    product_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The first 20 validation errors, `[{line, column, message}, ...]`.
    validation_errors_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    validation_error_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    inject_transient_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set only on the transition to COMPLETED (`_docs/architecture.md`, step 2.4).
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportAttempt(Base):
    __tablename__ = "import_attempts"
    __table_args__ = (
        UniqueConstraint("import_id", "attempt_number"),
        CheckConstraint(check_in("status", ATTEMPT_STATUSES), name="status"),
        CheckConstraint(check_in("error_code", FAILURE_CODES), name="error_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("imports.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # OpenTelemetry trace id (32 hex characters), filled by CIW-09.1.
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
