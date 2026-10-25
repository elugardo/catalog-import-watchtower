"""`alerts` and `agent_actions` (spec section 6)."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import AGENT_ACTIONS, ALERT_STATUSES, check_in


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # One alert per import in the MVP; a retry that fails again updates it.
        UniqueConstraint("import_id"),
        CheckConstraint(check_in("status", ALERT_STATUSES), name="status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    import_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("imports.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # Short operational reason; its wording is CIW-05's.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # Set by the worker's compare-and-set claim; drives the stale-claim reset.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentAction(Base):
    __tablename__ = "agent_actions"
    __table_args__ = (CheckConstraint(check_in("action", AGENT_ACTIONS), name="action"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("alerts.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Short, redacted JSON (never catalog content).
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
