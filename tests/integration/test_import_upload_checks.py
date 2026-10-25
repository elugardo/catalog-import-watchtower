"""`POST /api/imports`: the checks that need no parsing (spec section 4 F1).

Every rejected request leaves `imports`, `import_attempts` and `vendors`
exactly as they were (counted with SQL before and after).
"""

import pytest

from tests.integration.importing import (
    MAX_BYTES,
    Part,
    fixture_bytes,
    multipart_body,
    post_import,
    post_raw,
    table_counts,
)

VALID = fixture_bytes("valid.csv")
ERROR_KEYS = {"code", "message", "details"}


@pytest.fixture
def rejected(client, migrated_engine):
    """Send a request and assert it was rejected with no record written."""

    def _check(send, status: int, code: str) -> dict:
        before = table_counts(migrated_engine)
        response = send()
        after = table_counts(migrated_engine)
        assert response.status_code == status, response.text
        body = response.json()
        assert set(body) == ERROR_KEYS
        assert isinstance(body["details"], list)
        assert body["code"] == code, body
        assert after == before
        return body

    return _check


def accepted(response) -> dict:
    assert response.status_code == 201, response.text
    return response.json()


# ---- order ------------------------------------------------------------------


def test_filename_and_type_are_checked_before_size_and_size_before_encoding(client, rejected, ns):
    not_utf8_and_too_big = b"\xe9" * (300 * 1024)
    rejected(
        lambda: post_import(client, ns.name(), not_utf8_and_too_big, filename="catalog.txt"),
        400,
        "INVALID_CONTENT_TYPE",
    )
    rejected(
        lambda: post_import(client, ns.name(), not_utf8_and_too_big, filename="catalog.csv"),
        413,
        "FILE_TOO_LARGE",
    )


def test_presence_is_checked_before_values(client, rejected):
    # Invalid vendor name and no file: the missing field wins.
    rejected(lambda: post_import(client, "", None), 400, "MISSING_FIELD")


def test_field_values_are_checked_before_the_file_type(client, rejected):
    rejected(
        lambda: post_import(client, "   ", VALID, filename="catalog.txt"), 400, "INVALID_FIELD"
    )


# ---- missing fields -----------------------------------------------------------


def test_missing_vendor_name(client, rejected):
    rejected(lambda: post_import(client, None, VALID), 400, "MISSING_FIELD")


def test_missing_file(client, rejected, ns):
    rejected(lambda: post_import(client, ns.name(), None), 400, "MISSING_FIELD")


def test_file_sent_as_a_text_field(client, rejected, ns):
    parts = [Part("vendor_name", ns.name().encode()), Part("file", VALID)]
    rejected(lambda: post_raw(client, parts), 400, "INVALID_FIELD")


def test_vendor_name_sent_as_a_file_part(client, rejected):
    parts = [
        Part("vendor_name", b"Acme", filename="vendor.txt", content_type="text/plain"),
        Part("file", VALID, filename="valid.csv", content_type="text/csv"),
    ]
    rejected(lambda: post_raw(client, parts), 400, "INVALID_FIELD")


def test_non_multipart_body_is_missing_fields(client, rejected):
    rejected(lambda: client.post("/api/imports", json={"vendor_name": "x"}), 400, "MISSING_FIELD")


# ---- vendor_name --------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 81, "  " + "x" * 81 + "  ", "Sample\tFurnishings", "Sample\nFurnishings"],
    ids=["empty", "blank", "81-chars", "81-chars-trimmed", "tab", "newline"],
)
def test_invalid_vendor_name(client, rejected, name):
    rejected(lambda: post_import(client, name, VALID), 400, "INVALID_FIELD")


@pytest.mark.parametrize(
    ("base", "expected_length"),
    [("x" * 67, 80), ("  " + "x" * 67, 80), ("Café Möbel", None)],
    ids=["80-chars", "80-chars-with-spaces", "non-ascii"],
)
def test_valid_vendor_name(client, ns, base, expected_length):
    # The 12-character token plus a space makes the 67 characters up to 80.
    name = ns.name(base) + ("  " if base.startswith(" ") else "")
    body = accepted(post_import(client, name, VALID))
    assert body["status"] == "COMPLETED"
    assert body["vendor"]["display_name"] == name.strip()
    if expected_length:
        assert len(body["vendor"]["display_name"]) == expected_length


# ---- inject_transient_failure -----------------------------------------------


@pytest.mark.parametrize(("value", "stored"), [("true", True), ("false", False), (None, False)])
def test_injection_flag_accepted(client, ns, value, stored):
    body = accepted(post_import(client, ns.name(), VALID, inject=value))
    assert body["inject_transient_failure"] is stored


@pytest.mark.parametrize("value", ["True", "1", "yes", ""])
def test_injection_flag_rejected(client, rejected, ns, value):
    rejected(lambda: post_import(client, ns.name(), VALID, inject=value), 400, "INVALID_FIELD")


# ---- filename ---------------------------------------------------------------


@pytest.mark.parametrize("filename", ["catalog.txt", "catalog.csv.txt", "catalog"])
def test_filename_must_end_in_csv(client, rejected, ns, filename):
    rejected(
        lambda: post_import(client, ns.name(), VALID, filename=filename),
        400,
        "INVALID_CONTENT_TYPE",
    )


def test_csv_extension_ignores_case(client, ns):
    body = accepted(post_import(client, ns.name(), VALID, filename="catalog.CSV"))
    assert body["status"] == "COMPLETED"
    assert body["filename"] == "catalog.CSV"


# ---- content type -------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    [
        "text/csv",
        "text/plain",
        "application/vnd.ms-excel",
        "application/octet-stream",
        "text/csv; charset=utf-8",
        "application/octet-stream; foo=bar",
        "TEXT/CSV",
        "Application/Vnd.MS-Excel",
    ],
)
def test_allowed_content_types(client, ns, content_type):
    body = accepted(post_import(client, ns.name(), VALID, content_type=content_type))
    assert body["status"] == "COMPLETED"


def test_file_part_without_content_type_is_text_plain(client, ns):
    parts = [
        Part("vendor_name", ns.name().encode()),
        Part("file", VALID, filename="valid.csv", content_type=None),
    ]
    body = accepted(post_raw(client, parts))
    assert body["status"] == "COMPLETED"


def test_json_content_type_is_rejected(client, rejected, ns):
    rejected(
        lambda: post_import(client, ns.name(), VALID, content_type="application/json"),
        400,
        "INVALID_CONTENT_TYPE",
    )


# ---- encoding -----------------------------------------------------------------


def test_latin1_byte_is_invalid_encoding(client, rejected, ns):
    latin1 = "sku,name,price,quantity\nCAFE-1,Café Chair,10.00,1\n".encode("latin-1")
    assert b"\xe9" in latin1
    rejected(lambda: post_import(client, ns.name(), latin1), 400, "INVALID_ENCODING")


def test_utf16_with_bom_is_invalid_encoding(client, rejected, ns):
    utf16 = VALID.decode("utf-8").encode("utf-16")
    assert utf16[:2] in (b"\xff\xfe", b"\xfe\xff")
    rejected(lambda: post_import(client, ns.name(), utf16), 400, "INVALID_ENCODING")


def test_utf8_bom_is_accepted(client, ns):
    body = accepted(post_import(client, ns.name(), fixture_bytes("bom.csv"), filename="bom.csv"))
    assert body["status"] == "COMPLETED"


# ---- size ---------------------------------------------------------------------


def padded(size: int) -> bytes:
    data = VALID + b"\n" * (size - len(VALID))
    assert len(data) == size
    return data


def test_exactly_256_kib_is_accepted(client, ns):
    body = accepted(post_import(client, ns.name(), padded(MAX_BYTES)))
    assert body["status"] == "COMPLETED"
    assert body["product_count"] == 3


def test_one_byte_over_is_too_large(client, rejected, ns):
    rejected(lambda: post_import(client, ns.name(), padded(MAX_BYTES + 1)), 413, "FILE_TOO_LARGE")


def test_chunked_body_without_content_length_is_too_large(client, rejected, ns):
    body, content_type = _multipart(ns.name(), padded(MAX_BYTES + 1))

    def chunks():
        for start in range(0, len(body), 8192):
            yield body[start : start + 8192]

    def send():
        request = client.build_request(
            "POST", "/api/imports", content=chunks(), headers={"Content-Type": content_type}
        )
        assert "content-length" not in request.headers
        assert request.headers.get("transfer-encoding") == "chunked"
        return client.send(request)

    rejected(send, 413, "FILE_TOO_LARGE")


def test_five_mib_part_is_too_large(client, rejected, ns):
    rejected(lambda: post_import(client, ns.name(), padded(5 * 1024 * 1024)), 413, "FILE_TOO_LARGE")


def _multipart(vendor_name: str, data: bytes) -> tuple[bytes, str]:
    return multipart_body(
        [
            Part("vendor_name", vendor_name.encode()),
            Part("file", data, filename="valid.csv", content_type="text/csv"),
        ]
    )
