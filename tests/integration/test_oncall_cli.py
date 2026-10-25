"""`python -m app.oncall tools <tool> [args]`, the maintenance CLI (#10).

Each test runs the real command in a child process, as `docker compose exec`
would: one JSON object on stdout, logs on stderr, and the exit codes
0 DONE, 1 REFUSED, 2 usage, 3 NOT_FOUND, 4 unexpected error.
"""

import json
import os
import subprocess
import sys

import pytest

from app.services import agent_tools
from tests.integration.conftest import REPO_ROOT
from tests.integration.importing import import_row
from tests.integration.tooling import VALID, action_count, action_rows, injected

UNREACHABLE = "postgresql+psycopg://ciw:secret-pw@127.0.0.1:1/ciw"


def cli(*args: str, database_url: str, **env: str) -> subprocess.CompletedProcess[str]:
    environment = {k: v for k, v in os.environ.items() if k != "AGENT_ENABLED"}
    environment.update(DATABASE_URL=database_url, **env)
    return subprocess.run(
        [sys.executable, "-m", "app.oncall", "tools", *args],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def stdout_json(completed: subprocess.CompletedProcess[str]) -> dict:
    lines = completed.stdout.strip().splitlines()
    assert len(lines) == 1, completed.stdout
    return json.loads(lines[0])


def test_done_refused_and_not_found(client, database_url, migrated_engine, ns):
    body = injected(client, ns.name())
    alert_id = str(body["alert"]["id"])

    incident = cli("get_import_incident", alert_id, database_url=database_url)
    refused = cli("mark_needs_attention", alert_id, "needs a look", database_url=database_url)
    missing = cli("resolve_alert", str(2**63 - 1), database_url=database_url)
    beyond = cli("get_import_attempts", str(2**64), database_url=database_url)
    zero = cli("get_import_diagnostics", "0", database_url=database_url)

    assert incident.returncode == 0, incident.stderr
    assert stdout_json(incident) == agent_tools.get_import_incident(body["alert"]["id"])
    assert refused.returncode == 1
    assert stdout_json(refused)["refused_reason"] == "alert_not_in_progress"
    for completed in (missing, beyond, zero):
        assert completed.returncode == 3, completed.stderr
        assert stdout_json(completed)["outcome"] == "NOT_FOUND"
    # The CLI writes the same audit rows (the extra in-process call above adds one).
    assert [a["tool_name"] for a in action_rows(migrated_engine, body["alert"]["id"])] == [
        "get_import_incident",
        "mark_needs_attention",
        "get_import_incident",
    ]


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("no_such_tool",),
        ("retry_failed_import",),
        ("retry_failed_import", "1", "2"),
        ("mark_needs_attention", "1"),
        ("resolve_alert", "one"),
    ],
    ids=lambda a: " ".join(a) or "no tool",
)
def test_usage_errors_exit_2_without_touching_the_database(args, migrated_engine):
    before = action_count(migrated_engine)

    completed = cli(*args, database_url=UNREACHABLE)

    assert completed.returncode == 2
    assert completed.stdout == ""
    for name in agent_tools.TOOL_NAMES:
        assert name in completed.stderr
    assert action_count(migrated_engine) == before


def test_an_unexpected_error_exits_4_with_the_type_only():
    completed = cli("get_import_incident", "1", database_url=UNREACHABLE)

    assert completed.returncode == 4
    assert completed.stdout == ""
    assert completed.stderr.strip().splitlines() == ["error: OperationalError"]
    for secret in ("secret-pw", "127.0.0.1", "Traceback"):
        assert secret not in completed.stderr


def test_works_with_the_agent_disabled_and_never_sweeps(client, database_url, migrated_engine, ns):
    from app.schemas.upload import UploadRequest
    from app.services import importer

    # A PROCESSING import: the startup sweep would fail it; the CLI must not.
    stuck = importer.create_import(
        UploadRequest(
            vendor_name=ns.name(), filename="valid.csv", data=VALID, inject_transient_failure=False
        )
    )

    completed = cli(
        "get_import_attempts", str(stuck), database_url=database_url, AGENT_ENABLED="false"
    )

    assert completed.returncode == 0, completed.stderr
    assert stdout_json(completed) == {
        "outcome": "DONE",
        "import_id": stuck,
        "attempt_count": 0,
        "attempts": [],
    }
    assert import_row(migrated_engine, stuck)["status"] == "PROCESSING"
