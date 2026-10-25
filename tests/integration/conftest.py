"""Integration fixtures: the real PostgreSQL, migrated by Alembic (never `create_all`).

`migrated_engine` runs `alembic upgrade head` (non-destructive, a no-op when
the schema is already current) against `DATABASE_URL`, so the suite works on
the Compose `db` as well as in CI. Each test gets a `db` session inside one
outer transaction that is rolled back afterwards, so the suite leaves no rows
behind and can run twice in a row. Tests of the import API commit real
transactions from several connections, so they use `ns` instead: unique
vendor names whose rows are deleted at teardown. Destructive migration steps only ever run
in a throwaway database (`test_migration_round_trip.py`).
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the Alembic CLI in a child process (its logging config stays out of pytest)."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.fixture(scope="session")
def database_url() -> str:
    url = Settings().database_url
    try:
        with create_engine(url, connect_args={"connect_timeout": 3}).connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"PostgreSQL not reachable at the configured DATABASE_URL: {exc}")
    return url


@pytest.fixture(scope="session")
def migrated_engine(database_url) -> Iterator[Engine]:
    result = run_alembic(database_url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db(migrated_engine) -> Iterator[Session]:
    """A session whose every write is rolled back at the end of the test.

    `session.commit()` and `session.begin_nested()` work inside it as savepoints.
    """
    with migrated_engine.connect() as connection:
        outer = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            outer.rollback()


class Namespace:
    """Unique vendor names for one test, and the cleanup of every row they lead to.

    For tests that commit (the import API commits several transactions per
    request), where the rollback-only `db` fixture cannot be used.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.token = uuid.uuid4().hex[:12]

    def name(self, base: str = "Sample Furnishings") -> str:
        return f"{base} {self.token}"

    def cleanup(self) -> None:
        pattern = f"%{self.token}%"
        vendors = "SELECT id FROM vendors WHERE normalized_name LIKE :p"
        imports = f"SELECT id FROM imports WHERE vendor_id IN ({vendors})"
        alerts = f"SELECT id FROM alerts WHERE import_id IN ({imports})"
        with self.engine.begin() as connection:
            for statement in (
                f"DELETE FROM agent_actions WHERE alert_id IN ({alerts})",
                f"DELETE FROM alerts WHERE import_id IN ({imports})",
                f"DELETE FROM import_attempts WHERE import_id IN ({imports})",
                f"DELETE FROM imports WHERE vendor_id IN ({vendors})",
                f"DELETE FROM products WHERE vendor_id IN ({vendors})",
                "DELETE FROM vendors WHERE normalized_name LIKE :p",
            ):
                connection.execute(text(statement), {"p": pattern})


@pytest.fixture
def ns(migrated_engine) -> Iterator[Namespace]:
    namespace = Namespace(migrated_engine)
    try:
        yield namespace
    finally:
        namespace.cleanup()


@pytest.fixture
def client(make_client, database_url, migrated_engine) -> TestClient:
    """The app against the migrated database. Not a context manager: no startup sweep."""
    return make_client(DATABASE_URL=database_url)
