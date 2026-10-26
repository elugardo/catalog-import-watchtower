"""Integration fixtures: the real PostgreSQL, migrated by Alembic (never `create_all`).

The suite runs on its own database, `<configured database>_suite` on the
server `DATABASE_URL` names (`database_url`), never on the configured database
itself, so a live `oncall-agent` polling that database never sees the suite's
alerts. `migrated_engine` runs `alembic upgrade head` (non-destructive, a no-op when
the schema is already current) against it, so the suite works on
the Compose `db` as well as in CI. Each test gets a `db` session inside one
outer transaction that is rolled back afterwards, so the suite leaves no rows
behind and can run twice in a row. Tests of the import API commit real
transactions from several connections, so they use `ns` instead: unique
vendor names whose rows are deleted at teardown. Destructive migration steps only ever run
in a throwaway database (`throwaway_url`, used by `test_migration_round_trip.py` and
the empty-database list test).
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import DBAPIError
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


SUITE_DATABASE_SUFFIX = "_suite"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """The suite's own database, `<configured database>_suite`, on the configured server.

    Created if missing and kept between runs (so a warm run skips nothing but
    the creation). The suite never writes to the configured database itself
    (`ciw` in Compose), which is the one the app and a live `oncall-agent`
    use: the worker cannot claim an alert the suite created, and the
    developer's rows are not touched (`_docs/testing.md` -> *It leaves your
    data alone*). For the whole session `DATABASE_URL` points at the suite
    database, so code under test that builds its own settings lands there too.
    """
    configured = Settings().database_url
    try:
        with create_engine(configured, connect_args={"connect_timeout": 3}).connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"PostgreSQL not reachable at the configured DATABASE_URL: {exc}")
    url = make_url(configured)
    name = f"{url.database}{SUITE_DATABASE_SUFFIX}"
    admin = create_engine(configured, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            ).first()
            if exists is None:
                try:
                    connection.execute(text(f'CREATE DATABASE "{name}"'))
                except DBAPIError:  # fine only when a concurrent run created it first
                    created = connection.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
                    ).first()
                    if created is None:
                        raise
    finally:
        admin.dispose()
    suite_url = url.set(database=name).render_as_string(hide_password=False)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DATABASE_URL", suite_url)
        yield suite_url


@pytest.fixture(scope="session", autouse=True)
def suite_database(database_url) -> str:
    """Every integration test runs with `DATABASE_URL` on the suite database."""
    return database_url


@pytest.fixture(scope="session")
def migrated_engine(database_url) -> Iterator[Engine]:
    result = run_alembic(database_url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def throwaway_url(database_url) -> Iterator[str]:
    """A new, empty database on the same server (no migration run), dropped afterwards.

    For what must never touch the shared `db`: destructive migration steps,
    and the lists on a database with no rows at all.
    """
    name = f"ciw_throwaway_{uuid.uuid4().hex[:12]}"
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(database_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def isolated_db(throwaway_url, make_client) -> Iterator[tuple[str, Engine]]:
    """A migrated throwaway database, with the app's settings pointed at it.

    For code under test that touches rows it did not create, such as the
    startup sweep (it fails every `PROCESSING` import in the database): run
    against the shared `db`, it would change a developer's in-flight import.
    Yields `(url, engine)`; the database is dropped afterwards.
    """
    result = run_alembic(throwaway_url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    engine = create_engine(throwaway_url)
    make_client(DATABASE_URL=throwaway_url)  # sets DATABASE_URL for every create_app()
    try:
        yield throwaway_url, engine
    finally:
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
