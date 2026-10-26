"""Helpers for the worker tests: a worker config and a run on one claimed alert."""

from app.oncall import llm, poller
from tests.integration import tooling


def config(**overrides) -> poller.WorkerConfig:
    values = {
        "enabled": True,
        "provider": "anthropic",
        "model": "fake-model",
        "key_set": True,
        "poll_seconds": 0.1,
        "claim_timeout_seconds": 300.0,
        "max_tool_calls": 8,
        "timeout_seconds": 30.0,
    }
    values.update(overrides)
    return poller.WorkerConfig(**values)


def run_claimed(fake, alert_id: int, import_id: int, **limits) -> llm.RunSummary:
    """Claim one known alert and run the conversation on it (no poll)."""
    assert tooling.claim(alert_id)
    return llm.run_alert(
        fake,
        model="fake-model",
        alert_id=alert_id,
        import_id=import_id,
        limits=llm.Limits(**{"max_tool_calls": 8, "timeout_seconds": 30.0, **limits}),
    )
