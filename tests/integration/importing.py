"""Helpers for the import API tests: request building, row counts and product snapshots.

These tests commit real transactions (the import path commits several times
per request), so they cannot use the rollback-only `db` fixture. Each test
gets a `Namespace` (see `conftest.py`) whose vendor names carry a unique
token; its teardown deletes every row reachable from those vendors, so the
suite leaves the database as it found it and passes twice in a row.
"""

import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
MAX_BYTES = 256 * 1024
HEADER = b"sku,name,price,quantity\n"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def csv_rows(count: int, *, prefix: str = "SKU", start: int = 1) -> bytes:
    """`count` valid data rows (no header)."""
    return b"".join(
        f"{prefix}-{n:05d},Generated Item {n},{n}.25,{n % 7}\n".encode()
        for n in range(start, start + count)
    )


def post_import(
    client: TestClient,
    vendor_name: str | None,
    content: bytes | None,
    *,
    filename: str = "valid.csv",
    content_type: str | None = "text/csv",
    inject: str | None = None,
) -> httpx.Response:
    """A regular multipart upload through httpx (`None` leaves the field out)."""
    data: dict[str, str] = {}
    if vendor_name is not None:
        data["vendor_name"] = vendor_name
    if inject is not None:
        data["inject_transient_failure"] = inject
    files: dict[str, Any] = {}
    if content is not None:
        files["file"] = (filename, content, content_type)
    return client.post("/api/imports", data=data, files=files or None)


class Part:
    """One hand-built multipart part, for cases httpx cannot express (no Content-Type)."""

    def __init__(
        self,
        name: str,
        value: bytes,
        *,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> None:
        self.name, self.value, self.filename, self.content_type = (
            name,
            value,
            filename,
            content_type,
        )

    def encode(self, boundary: bytes) -> bytes:
        disposition = f'form-data; name="{self.name}"'
        if self.filename is not None:
            disposition += f'; filename="{self.filename}"'
        headers = [f"Content-Disposition: {disposition}".encode()]
        if self.content_type is not None:
            headers.append(f"Content-Type: {self.content_type}".encode())
        return (
            b"--" + boundary + b"\r\n" + b"\r\n".join(headers) + b"\r\n\r\n" + self.value + b"\r\n"
        )


def multipart_body(parts: Iterable[Part]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex.encode()
    body = b"".join(part.encode(boundary) for part in parts) + b"--" + boundary + b"--\r\n"
    return body, f"multipart/form-data; boundary={boundary.decode()}"


def post_raw(client: TestClient, parts: Iterable[Part]) -> httpx.Response:
    body, content_type = multipart_body(parts)
    return client.post("/api/imports", content=body, headers={"Content-Type": content_type})


def table_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("imports", "import_attempts", "vendors")
        }


def products_snapshot(engine: Engine, vendor_id: int) -> list[dict[str, Any]]:
    """Every column of every product of the vendor, by id."""
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT * FROM products WHERE vendor_id = :v ORDER BY id"), {"v": vendor_id}
        ).mappings()
        return [dict(row) for row in rows]


def all_products(engine: Engine) -> list[dict[str, Any]]:
    """The products snapshot of #7: every product of every vendor, `updated_at` included."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, vendor_id, sku, normalized_sku, name, price_cents, quantity,"
                " updated_at FROM products ORDER BY id"
            )
        ).mappings()
        return [dict(row) for row in rows]


def alert_rows(engine: Engine, import_id: int) -> list[dict[str, Any]]:
    """Every `alerts` row of the import (at most one, by the unique constraint)."""
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT * FROM alerts WHERE import_id = :i ORDER BY id"), {"i": import_id}
        ).mappings()
        return [dict(row) for row in rows]


def products_by_sku(engine: Engine, vendor_id: int) -> dict[str, dict[str, Any]]:
    return {row["normalized_sku"]: row for row in products_snapshot(engine, vendor_id)}


def import_row(engine: Engine, import_id: int) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(
            connection.execute(text("SELECT * FROM imports WHERE id = :i"), {"i": import_id})
            .mappings()
            .one()
        )


def assert_failed_validation(body: dict[str, Any]) -> None:
    assert body["status"] == "FAILED", body
    assert body["failure_code"] == "VALIDATION_ERROR"
    assert body["product_count"] is None
    assert body["completed_at"] is None
    assert body["attempts"][0]["status"] == "FAILED"
    assert body["attempts"][0]["error_code"] == "VALIDATION_ERROR"
    assert body["attempts"][0]["finished_at"] is not None
