"""Worker tests: the real loop, dispatch and tools on the real Postgres, with a fake LLM.

The integration fixtures (`database_url` on the suite database, `client`,
`ns`, `isolated_db`, ...) are shared from `tests/integration/conftest.py`.
Tests that poll (`poller.poll_once` picks the oldest `OPEN` alert and resets
every stale claim in the database) run on `isolated_db`; tests that claim one
known alert and call `llm.run_alert` use `client` and `ns`.
"""

import pytest

from tests.integration.conftest import *


@pytest.fixture(autouse=True)
def _no_provider_key(monkeypatch):
    """No test sees a real key: the variable is removed for every worker test."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
