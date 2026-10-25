"""Query rules of the four list endpoints, before and without any database (spec section 7).

Every request here is rejected by validation before the service layer runs,
or is answered while the database is unreachable, so an unreachable
`DATABASE_URL` is enough. The behaviour of valid values, which needs rows,
is in `tests/integration/test_list_*.py`.
"""

import pytest
from fastapi.testclient import TestClient

from app.schemas.query import parse_query_integer

UNREACHABLE_DB = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nothing"
ERROR_KEYS = {"code", "message", "details"}
LISTS = ["/api/imports", "/api/vendors", "/api/products", "/api/alerts"]

BAD_LIMITS = ["0", "101", "-1", "abc", "1.5", "5.0", "+5", "%205", "1e2", ""]
BAD_OFFSETS = ["-1", "abc", "1.5", ""]
BAD_VENDOR_IDS = ["abc", "1.5", "5.0", ""]


@pytest.fixture
def client(make_client) -> TestClient:
    return TestClient(make_client(DATABASE_URL=UNREACHABLE_DB).app, raise_server_exceptions=False)


def assert_invalid_query(response, parameter: str) -> None:
    assert response.status_code == 400, response.text
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["code"] == "INVALID_QUERY"
    assert isinstance(body["details"], list)
    assert parameter in body["message"]


@pytest.mark.parametrize("path", LISTS)
@pytest.mark.parametrize("value", BAD_LIMITS)
def test_bad_limit_is_invalid_query(client, path, value):
    assert_invalid_query(client.get(f"{path}?limit={value}"), "limit")


@pytest.mark.parametrize("path", LISTS)
@pytest.mark.parametrize("value", BAD_OFFSETS)
def test_bad_offset_is_invalid_query(client, path, value):
    assert_invalid_query(client.get(f"{path}?offset={value}"), "offset")


@pytest.mark.parametrize("value", BAD_VENDOR_IDS)
def test_bad_vendor_id_is_invalid_query(client, value):
    assert_invalid_query(client.get(f"/api/products?vendor_id={value}"), "vendor_id")


def test_the_first_bad_parameter_is_named_and_every_error_is_in_details(client):
    response = client.get("/api/products?limit=abc&offset=-1")

    assert_invalid_query(response, "limit")
    locations = [detail["loc"] for detail in response.json()["details"]]
    assert ["query", "limit"] in locations
    assert ["query", "offset"] in locations


@pytest.mark.parametrize(
    ("method", "path"),
    [
        (method, path)
        for path in ("/api/vendors", "/api/products", "/api/alerts")
        for method in ("post", "put", "delete")
    ]
    + [("put", "/api/imports"), ("delete", "/api/imports")],
)
def test_other_methods_on_the_lists_are_405_in_the_error_shape(client, method, path):
    response = client.request(method.upper(), path)

    assert response.status_code == 405
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.parametrize("path", LISTS)
def test_database_unreachable_is_500_without_the_dsn(client, path):
    response = client.get(path)

    assert response.status_code == 500
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["code"] == "INTERNAL_ERROR"
    for fragment in ("nobody", "nothing", "127.0.0.1", "postgresql", "psycopg", ":1/"):
        assert fragment not in response.text, fragment


def test_health_stays_200_degraded_while_the_lists_fail(client):
    body = client.get("/api/health").json()
    assert (body["status"], body["db"]) == ("degraded", "error")


# ---- the integer grammar ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("5", 5),
        ("05", 5),
        ("000", 0),
        ("-1", -1),
        ("-0", 0),
        ("9223372036854775807", 2**63 - 1),
        ("9223372036854775808", 2**63),
        # More than 19 significant digits: beyond BIGINT whatever it is.
        ("99999999999999999999", 2**63),
        ("-99999999999999999999", -(2**63)),
        ("000000000000000000000000001", 1),
        ("1" + "0" * 5000, 2**63),
    ],
)
def test_query_integer_grammar_accepts(raw, value):
    assert parse_query_integer(raw) == value


@pytest.mark.parametrize(
    "raw", ["", " 5", "5 ", "+5", "5.0", "1.5", "1e2", "abc", "1_000", "--1", "-", "٥", "5\n"]
)
def test_query_integer_grammar_rejects(raw):
    with pytest.raises(ValueError):
        parse_query_integer(raw)
