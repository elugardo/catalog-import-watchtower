"""`GET /api/imports/{id}` (spec section 4 F3 read side, section 7) and the response shape."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import text

from tests.integration.importing import fixture_bytes, post_import

OPENAPI = Path(__file__).resolve().parents[2] / "openapi.yaml"
VALID = fixture_bytes("valid.csv")


@pytest.fixture(scope="module")
def schemas() -> dict[str, Any]:
    return yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))["components"]["schemas"]


def properties(schemas: dict[str, Any], name: str) -> set[str]:
    """Every property of a component, following `allOf` and `$ref`."""
    schema = schemas[name]
    found = set(schema.get("properties", {}))
    for part in schema.get("allOf", []):
        if "$ref" in part:
            found |= properties(schemas, part["$ref"].rsplit("/", 1)[-1])
        found |= set(part.get("properties", {}))
    return found


def timestamps(value: Any, key: str = "") -> list[str]:
    if isinstance(value, dict):
        return [t for k, v in value.items() for t in timestamps(v, k)]
    if isinstance(value, list):
        return [t for item in value for t in timestamps(item, key)]
    if isinstance(value, str) and (key.endswith("_at")):
        return [value]
    return []


def add_incident_rows(engine, import_id: int) -> None:
    """A second SUCCEEDED attempt, an alert and two agent actions, inserted directly."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO import_attempts (import_id, attempt_number, status, finished_at)"
                " VALUES (:i, 2, 'SUCCEEDED', now())"
            ),
            {"i": import_id},
        )
        alert_id = connection.execute(
            text(
                "INSERT INTO alerts (import_id, status, reason) VALUES (:i, 'RESOLVED', 'test')"
                " RETURNING id"
            ),
            {"i": import_id},
        ).scalar_one()
        for offset, action in ((0, "RUN_STARTED"), (1, "RUN_FINISHED")):
            connection.execute(
                text(
                    "INSERT INTO agent_actions (alert_id, action, tool_name, reason_summary,"
                    " result, created_at) VALUES (:a, :action, NULL, 'r', '{\"ok\": true}',"
                    " now() + make_interval(secs => :offset))"
                ),
                {"a": alert_id, "action": action, "offset": offset},
            )


def test_unknown_import_is_404(client):
    response = client.get("/api/imports/999999999")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == "NOT_FOUND"
    assert body["details"] == []


def test_derived_fields_and_embedded_rows(client, migrated_engine, ns):
    created = post_import(client, ns.name(), VALID).json()
    add_incident_rows(migrated_engine, created["id"])

    body = client.get(f"/api/imports/{created['id']}").json()

    assert body["attempt_count"] == 2
    assert body["recovered"] is True
    assert [a["number"] for a in body["attempts"]] == [1, 2]
    assert isinstance(body["alert"], dict)
    assert body["alert"]["status"] == "RESOLVED"
    assert [a["action"] for a in body["agent_actions"]] == ["RUN_STARTED", "RUN_FINISHED"]


def test_two_attempts_on_a_failed_import_are_not_recovered(client, migrated_engine, ns):
    created = post_import(
        client, ns.name(), fixture_bytes("invalid.csv"), filename="invalid.csv"
    ).json()
    add_incident_rows(migrated_engine, created["id"])

    body = client.get(f"/api/imports/{created['id']}").json()

    assert body["status"] == "FAILED"
    assert body["attempt_count"] == 2
    assert body["recovered"] is False


@pytest.mark.parametrize("fixture", ["valid.csv", "invalid.csv"])
def test_exact_property_sets(client, migrated_engine, schemas, ns, fixture):
    created = post_import(client, ns.name(), fixture_bytes(fixture), filename=fixture).json()
    add_incident_rows(migrated_engine, created["id"])
    fetched = client.get(f"/api/imports/{created['id']}").json()

    for body in (created, fetched):
        assert set(body) == properties(schemas, "ImportDetail")
        assert set(body["vendor"]) == properties(schemas, "Vendor")
        for attempt in body["attempts"]:
            assert set(attempt) == properties(schemas, "Attempt")
        for error in body["validation_errors"]:
            assert set(error) == properties(schemas, "ValidationError")
        for stamp in timestamps(body):
            assert stamp.endswith("Z"), stamp
    assert set(fetched["alert"]) == properties(schemas, "Alert")
    assert len(fetched["agent_actions"]) == 2
    for action in fetched["agent_actions"]:
        assert set(action) == properties(schemas, "AgentAction")
    if fixture == "invalid.csv":
        assert fetched["validation_errors"], "the failed import carries its errors"
