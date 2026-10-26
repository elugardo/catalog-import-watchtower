"""The worker's poll: reset stale claims, claim the oldest `OPEN` alert, run it.

`_docs/architecture.md` -> *On-call worker loop*, steps 1 and 2, with the
claim helpers of `app/services/alerts.py`. The worker never claims without
credentials: `idle_reason` names the first missing one (never a value) and
the worker then only waits for its stop signal.

Configuration is read from the environment once at start (`WorkerConfig`);
`AGENT_ENABLED` comes from `app.settings`, the same parsing as `/api/health`.
The provider key is not read here: only whether `ANTHROPIC_API_KEY` is set and
non-empty. The SDK reads the value itself (`llm.make_client`).
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app import telemetry
from app.db import get_sessionmaker
from app.models import Alert
from app.oncall import llm
from app.services import alerts
from app.settings import get_settings

log = logging.getLogger("app.oncall.poller")

KEY_VARIABLE = "ANTHROPIC_API_KEY"
# How many of the oldest `OPEN` alerts one poll tries to claim before giving up.
CLAIM_CANDIDATES = 10


def _number(name: str, default: float, kind: type = float) -> Any:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return kind(default)
    try:
        value = kind(raw)
    except ValueError:
        value = 0
    if not (value > 0 and math.isfinite(value)):  # also NaN, inf and overflowing values
        # Names the variable, never the value; the worker then idles with this reason.
        raise ValueError(f"{name} is not a positive {'integer' if kind is int else 'number'}")
    return value


@dataclass(frozen=True)
class WorkerConfig:
    enabled: bool
    provider: str
    model: str
    key_set: bool
    poll_seconds: float = 10.0
    claim_timeout_seconds: float = 300.0
    max_tool_calls: int = 8
    timeout_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> WorkerConfig:
        return cls(
            enabled=get_settings().agent_enabled,
            provider=os.environ.get("LLM_PROVIDER", "").strip(),
            model=os.environ.get("LLM_MODEL", "").strip(),
            key_set=bool(os.environ.get(KEY_VARIABLE, "").strip()),
            poll_seconds=_number("AGENT_POLL_SECONDS", 10),
            claim_timeout_seconds=_number("AGENT_CLAIM_TIMEOUT_SECONDS", 300),
            max_tool_calls=_number("AGENT_MAX_TOOL_CALLS", 8, int),
            timeout_seconds=_number("AGENT_TIMEOUT_SECONDS", 120),
        )

    @property
    def limits(self) -> llm.Limits:
        return llm.Limits(self.max_tool_calls, self.timeout_seconds)


def idle_reason(config: WorkerConfig) -> str | None:
    """Why the worker must not claim anything, or None when it may. Never quotes a value."""
    if not config.enabled:
        return "AGENT_ENABLED is not true"
    if config.provider != llm.PROVIDER:
        return f"LLM_PROVIDER is not {llm.PROVIDER}"
    if not config.key_set:
        return f"{KEY_VARIABLE} is not set"
    if not config.model:
        return "LLM_MODEL is not set"
    return None


def claim_next() -> tuple[int, int] | None:
    """Claim the oldest `OPEN` alert; `(alert_id, import_id)`, or None when none was claimed.

    Each claim is its own compare-and-set transaction (`alerts.claim_alert`):
    an alert another worker claimed first is skipped.
    """
    with get_sessionmaker()() as session:
        with session.begin():
            candidates = session.execute(
                select(Alert.id, Alert.import_id)
                .where(Alert.status == "OPEN")
                .order_by(Alert.created_at, Alert.id)
                .limit(CLAIM_CANDIDATES)
            ).all()
        for alert_id, import_id in candidates:
            with session.begin():
                if alerts.claim_alert(session, alert_id):
                    return alert_id, import_id
    return None


def poll_once(client: Any, config: WorkerConfig) -> llm.RunSummary | None:
    """One poll: reset stale claims, claim one alert and run it. None when nothing was claimed."""
    with get_sessionmaker()() as session, session.begin():
        reset = alerts.reset_stale_claims(session, config.claim_timeout_seconds)
    for alert_id in reset:
        log.info(
            "oncall-agent: stale claim on alert %s returned to OPEN",
            alert_id,
            extra=telemetry.log_ids(alert_id=alert_id),
        )

    claimed = claim_next()
    if claimed is None:
        return None
    alert_id, import_id = claimed
    log.info(
        "oncall-agent: claimed alert %s (import %s)",
        alert_id,
        import_id,
        extra=telemetry.log_ids(alert_id=alert_id, import_id=import_id),
    )
    return llm.run_alert(
        client, model=config.model, alert_id=alert_id, import_id=import_id, limits=config.limits
    )
