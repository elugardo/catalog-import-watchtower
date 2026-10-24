"""`/api/health` against the real PostgreSQL (`DATABASE_URL`, default: the Compose `db` on localhost:5432)."""

import pytest
from sqlalchemy import create_engine, text

from app.settings import Settings


@pytest.fixture(scope="module")
def postgres_url() -> str:
    # Same resolution as the app itself: environment, then `.env`, then the default.
    url = Settings().database_url
    try:
        with create_engine(url, connect_args={"connect_timeout": 3}).connect() as connection:
            version = connection.execute(text("SHOW server_version")).scalar_one()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"PostgreSQL not reachable at the configured DATABASE_URL: {exc}")
    assert version.startswith("16"), f"expected PostgreSQL 16, got {version}"
    return url


def test_health_reports_db_ok_against_real_postgres(make_client, postgres_url):
    client = make_client(DATABASE_URL=postgres_url)

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "db", "agent_enabled", "version"}
    assert body["db"] == "ok"
    assert body["status"] == "ok"
