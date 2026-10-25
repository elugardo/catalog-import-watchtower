"""`GET /api/alerts` (spec section 7), and all four lists on a database with no rows.

The failed imports' alerts are the ones CIW-05 (#7) writes; their status, the
shared `created_at` and the alert of the completed import are set directly.
"""

import pytest

from tests.integration.conftest import run_alembic
from tests.integration.contract import assert_matches, item_keys, sql, walk
from tests.integration.importing import fixture_bytes, post_import

LISTS = ["/api/imports", "/api/vendors", "/api/products", "/api/alerts"]


def test_every_list_is_empty_on_a_fresh_database(make_client, throwaway_url):
    result = run_alembic(throwaway_url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    client = make_client(DATABASE_URL=throwaway_url)

    for path in LISTS:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.json() == {"items": [], "total": 0}, path


@pytest.fixture
def three_alerts(client, migrated_engine, ns) -> dict[str, dict]:
    """OPEN on a validation failure of A, NEEDS_ATTENTION on a failure of B,
    RESOLVED on a COMPLETED import of A with a directly-inserted attempt 2.

    OPEN and NEEDS_ATTENTION are inserted in one transaction, so they share one
    `created_at`; RESOLVED is inserted afterwards with an older `created_at`, so
    `id` order and `created_at` order differ.
    """
    invalid = fixture_bytes("invalid.csv")
    failed_a = post_import(client, ns.name("Vendor A"), invalid, filename="invalid.csv").json()
    failed_b = post_import(client, ns.name("Vendor B"), invalid, filename="b.csv").json()
    completed = post_import(client, ns.name("Vendor A"), fixture_bytes("valid.csv")).json()
    sql(
        migrated_engine,
        "INSERT INTO import_attempts (import_id, attempt_number, status, finished_at)"
        " VALUES (:i, 2, 'SUCCEEDED', now())",
        i=completed["id"],
    )
    # Both failures already have their OPEN alert (#7); B's is moved on and
    # both are given one shared `created_at`, for the tie-break.
    open_id, attention_id = failed_a["alert"]["id"], failed_b["alert"]["id"]
    sql(
        migrated_engine,
        "UPDATE alerts SET created_at = now(),"
        " status = CASE WHEN id = :b THEN 'NEEDS_ATTENTION' ELSE status END"
        " WHERE id IN (:a, :b) RETURNING id",
        a=open_id,
        b=attention_id,
    )
    (resolved,) = sql(
        migrated_engine,
        "INSERT INTO alerts (import_id, status, reason, created_at)"
        " VALUES (:i, 'RESOLVED', 'test', now() - interval '1 hour') RETURNING id",
        i=completed["id"],
    )
    return {
        "open": {"id": open_id, "import": failed_a},
        "attention": {"id": attention_id, "import": failed_b},
        "resolved": {"id": resolved.id, "import": completed},
    }


def test_alerts_of_every_status_newest_first_with_their_import_summary(client, three_alerts):
    ours = {alert["id"] for alert in three_alerts.values()}

    listed = [item for item in walk(client, "/api/alerts") if item["id"] in ours]

    open_id, attention_id = three_alerts["open"]["id"], three_alerts["attention"]["id"]
    tie = [max(open_id, attention_id), min(open_id, attention_id)]
    assert [item["id"] for item in listed] == [*tie, three_alerts["resolved"]["id"]]
    by_id = {item["id"]: item for item in listed}
    for key, status in (
        ("open", "OPEN"),
        ("attention", "NEEDS_ATTENTION"),
        ("resolved", "RESOLVED"),
    ):
        alert = three_alerts[key]
        item = by_id[alert["id"]]
        source = alert["import"]
        assert set(item) == item_keys("AlertListItem")
        assert_matches(item, "AlertListItem")
        assert item["status"] == status
        assert item["import_id"] == source["id"]
        assert item["import_status"] == source["status"]
        assert item["failure_code"] == source["failure_code"]
        assert item["filename"] == source["filename"]
        assert item["vendor_display_name"] == source["vendor"]["display_name"]
    assert by_id[three_alerts["open"]["id"]]["failure_code"] == "VALIDATION_ERROR"
    assert by_id[three_alerts["resolved"]["id"]]["import_status"] == "COMPLETED"
    assert by_id[three_alerts["resolved"]["id"]]["failure_code"] is None


def test_alert_list_page_matches_the_contract(client, three_alerts):
    body = client.get("/api/alerts", params={"limit": 100}).json()

    assert_matches(body, "AlertList")
