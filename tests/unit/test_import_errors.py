"""Error mapping of the import routes and startup with no database (no network, no Postgres).

Every request here is rejected before the service layer touches the
database, so an unreachable `DATABASE_URL` is enough.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from app.schemas.upload import (
    UploadRejected,
    check_encoding,
    check_file_type,
    clean_vendor_name,
    parse_injection_flag,
)

UNREACHABLE_DB = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nothing"
ERROR_KEYS = {"code", "message", "details"}
VALID = b"sku,name,price,quantity\nA-1,Chair,1.00,1\n"


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client(DATABASE_URL=UNREACHABLE_DB)


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert isinstance(body["details"], list)
    assert body["code"] == code


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", "1.5", "99999999999999999999999"])
def test_malformed_import_id_is_404_never_422(client, bad_id):
    assert_error(client.get(f"/api/imports/{bad_id}"), 404, "NOT_FOUND")


def test_empty_post_is_missing_field(client):
    assert_error(client.post("/api/imports"), 400, "MISSING_FIELD")


def test_missing_file_is_missing_field(client):
    assert_error(client.post("/api/imports", data={"vendor_name": "x"}), 400, "MISSING_FIELD")


def test_missing_vendor_is_missing_field(client):
    response = client.post("/api/imports", files={"file": ("a.csv", VALID, "text/csv")})
    assert_error(response, 400, "MISSING_FIELD")


def test_malformed_multipart_is_invalid_field(client):
    response = client.post(
        "/api/imports",
        content=b"--b\r\nContent-Disposition: form-data\r\n\r\nx\r\n--b--\r\n",
        headers={"Content-Type": "multipart/form-data; boundary=b"},
    )
    assert_error(response, 400, "INVALID_FIELD")


def test_oversized_text_field_is_invalid_field(client):
    response = client.post("/api/imports", data={"vendor_name": "x" * (2 * 1024 * 1024)})
    assert_error(response, 400, "INVALID_FIELD")


# ---- the pure checks ----------------------------------------------------------


def rejection(call, *args) -> str:
    with pytest.raises(UploadRejected) as caught:
        call(*args)
    return caught.value.code


def test_vendor_name_rules():
    assert clean_vendor_name("  Café Möbel ") == "Café Möbel"
    assert clean_vendor_name("x" * 80) == "x" * 80
    for bad in ("", "  ", "x" * 81, "a\tb", "a\nb", "a b"):
        assert rejection(clean_vendor_name, bad) == "INVALID_FIELD", repr(bad)


def test_injection_flag_rules():
    assert parse_injection_flag(None) is False
    assert parse_injection_flag("false") is False
    assert parse_injection_flag("true") is True
    for bad in ("True", "1", "yes", ""):
        assert rejection(parse_injection_flag, bad) == "INVALID_FIELD"


def test_file_type_rules():
    check_file_type("a.CSV", "TEXT/CSV; charset=utf-8")
    check_file_type("a.csv", None)
    check_file_type("a.csv", "")
    for name, content_type in (
        ("a.txt", "text/csv"),
        ("a.csv.txt", "text/csv"),
        ("a", "text/csv"),
        ("", "text/csv"),
        ("a.csv", "application/json"),
    ):
        assert rejection(check_file_type, name, content_type) == "INVALID_CONTENT_TYPE"


def test_encoding_rules():
    check_encoding(b"\xef\xbb\xbfsku")
    assert rejection(check_encoding, b"caf\xe9") == "INVALID_ENCODING"
    assert rejection(check_encoding, "sku".encode("utf-16")) == "INVALID_ENCODING"


# ---- startup with the database down -------------------------------------------


def test_app_starts_with_the_database_unreachable(make_client, caplog):
    caplog.set_level(logging.DEBUG)
    app = make_client(DATABASE_URL=UNREACHABLE_DB).app

    with TestClient(app) as client:  # runs the lifespan, and so the sweep
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    sweep_logs = [r for r in caplog.records if "startup sweep" in r.getMessage()]
    assert len(sweep_logs) == 1
    message = sweep_logs[0].getMessage()
    assert message == "startup sweep skipped: OperationalError"
    assert sweep_logs[0].exc_info is None
    for record in caplog.records:
        assert "nobody" not in record.getMessage()
