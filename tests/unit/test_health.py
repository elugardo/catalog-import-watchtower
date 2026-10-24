"""`/api/health` and the app shell with no database reachable (no network, no Postgres)."""

import time

from fastapi.testclient import TestClient

# Nothing listens on port 1; connecting is refused immediately on every platform.
UNREACHABLE_DB = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nothing"

HEALTH_KEYS = {"status", "db", "agent_enabled", "version"}
ERROR_KEYS = {"code", "message", "details"}


def test_unexpected_exception_is_a_500_in_the_error_shape(make_client, monkeypatch):
    import app.routers.health as health_module

    def exploding_probe() -> bool:
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(health_module, "check_database", exploding_probe)
    # Let the response through instead of re-raising the exception in the test.
    client = TestClient(make_client(DATABASE_URL=UNREACHABLE_DB).app, raise_server_exceptions=False)

    response = client.get("/api/health")

    assert response.status_code == 500
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["code"] == "INTERNAL_ERROR"
    assert "probe exploded" not in body["message"]


def test_health_is_200_with_exactly_four_keys_when_db_unreachable(make_client):
    client = make_client(DATABASE_URL=UNREACHABLE_DB, AGENT_ENABLED="false", APP_VERSION="dev")

    started = time.monotonic()
    response = client.get("/api/health")
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    body = response.json()
    assert set(body) == HEALTH_KEYS
    assert body["db"] == "error"
    assert body["status"] == "degraded"
    assert body["agent_enabled"] is False
    assert body["version"] == "dev"
    # Guards the connect timeout: without it psycopg waits ~130 s on a host that
    # does not refuse (observed). Linux refuses instantly; Windows can take a few
    # seconds per attempt, hence the loose bound.
    assert elapsed < 15, f"health took {elapsed:.1f}s with the database down"


def test_health_reports_agent_enabled_and_version_from_environment(make_client):
    client = make_client(DATABASE_URL=UNREACHABLE_DB, AGENT_ENABLED="true", APP_VERSION="abc123")

    body = client.get("/api/health").json()

    assert body["agent_enabled"] is True
    assert body["version"] == "abc123"


def test_unknown_api_path_is_404_in_the_error_shape(make_client, tmp_path):
    # With a bundle present, only the API check can produce this 404 (never the SPA fallback).
    (tmp_path / "index.html").write_text("<title>shell</title>")
    client = make_client(DATABASE_URL=UNREACHABLE_DB, STATIC_DIR=str(tmp_path))

    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert isinstance(body["message"], str) and body["message"]
    assert body["details"] == []
    assert set(body) == {"code", "message", "details"}


def test_unknown_api_method_is_in_the_error_shape(make_client):
    client = make_client(DATABASE_URL=UNREACHABLE_DB)

    response = client.post("/api/health")

    assert response.status_code == 405
    assert set(response.json()) == {"code", "message", "details"}


def test_non_api_paths_serve_the_spa_index(make_client, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>Catalog Import Watchtower</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('bundle')")
    client = make_client(DATABASE_URL=UNREACHABLE_DB, STATIC_DIR=str(tmp_path))

    for path in ("/", "/anything", "/imports/42"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html")
        assert "Catalog Import Watchtower" in response.text
        assert "access-control-allow-origin" not in response.headers

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "bundle" in asset.text


def test_spa_fallback_never_escapes_the_static_dir(make_client, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<title>shell</title>")
    (tmp_path / "secret.txt").write_text("outside")
    client = make_client(DATABASE_URL=UNREACHABLE_DB, STATIC_DIR=str(static))

    # Percent-encoded so the client does not normalise the `..` away before sending.
    response = client.get("/%2e%2e/secret.txt")

    assert "outside" not in response.text
    assert response.status_code == 200  # falls back to the SPA index


def test_missing_bundle_is_a_404_in_the_error_shape(make_client, tmp_path):
    client = make_client(DATABASE_URL=UNREACHABLE_DB, STATIC_DIR=str(tmp_path / "nowhere"))

    response = client.get("/")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
