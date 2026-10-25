"""The revision upgrades, downgrades and upgrades again, in a throwaway database.

The test creates its own database on the same server, runs the destructive
`downgrade base` only there, and drops it at the end, so a developer's data in
the Compose `db` is never touched. CI runs the same sequence against its
service database as separate steps of the `backend` job.
"""

from sqlalchemy import create_engine, text

from tests.integration.conftest import run_alembic


def _public_tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables"
                        " WHERE table_schema = 'public'"
                    )
                ).scalars()
            )
    finally:
        engine.dispose()


SIX_TABLES = {"vendors", "products", "imports", "import_attempts", "alerts", "agent_actions"}


def test_upgrade_downgrade_upgrade_and_check(throwaway_url):
    def alembic(*args: str) -> str:
        result = run_alembic(throwaway_url, *args)
        assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"
        return result.stdout + result.stderr

    alembic("upgrade", "head")
    assert _public_tables(throwaway_url) == SIX_TABLES | {"alembic_version"}

    alembic("downgrade", "base")
    assert _public_tables(throwaway_url) == {"alembic_version"}

    alembic("upgrade", "head")
    second = alembic("upgrade", "head")
    assert "Running upgrade" not in second  # already at head: a no-op
    assert _public_tables(throwaway_url) == SIX_TABLES | {"alembic_version"}

    assert "No new upgrade operations detected" in alembic("check")
