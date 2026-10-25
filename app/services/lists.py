"""Read-only queries behind the four list endpoints (spec section 7).

Every list is a plain `SELECT` ordered by its timestamp descending, then `id`
descending, with `LIMIT` / `OFFSET`; `total` is a `count(*)` under the same
filter and ignores paging. An `offset` at or past `total` returns no items
without running the page query, so an offset beyond the `BIGINT` range is an
empty page, never a database error. A `vendor_id` that cannot name a vendor
(zero, negative, beyond `BIGINT`) is an empty list. No cache; nothing here
writes or logs.
"""

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.models import Alert, Import, Product, Vendor
from app.schemas import AlertListItemOut, ImportOut, Page, ProductOut, VendorOut
from app.schemas.query import MAX_BIGINT
from app.services.importer import import_summary


def _page(session: Session, query: Select[Any], limit: int, offset: int) -> tuple[list[Any], int]:
    """The rows of one page of `query` and the count of all its rows."""
    total = session.execute(
        select(func.count()).select_from(query.order_by(None).subquery())
    ).scalar_one()
    if offset >= total:
        return [], total
    rows = session.execute(query.limit(limit).offset(offset))
    return list(rows), total


def list_imports(limit: int, offset: int) -> Page[ImportOut]:
    query = select(Import).order_by(Import.created_at.desc(), Import.id.desc())
    with get_sessionmaker()() as session:
        rows, total = _page(session, query, limit, offset)
        items = [ImportOut.model_validate(import_summary(row.Import)) for row in rows]
    return Page[ImportOut](items=items, total=total)


def list_vendors(limit: int, offset: int) -> Page[VendorOut]:
    query = select(Vendor).order_by(Vendor.created_at.desc(), Vendor.id.desc())
    with get_sessionmaker()() as session:
        rows, total = _page(session, query, limit, offset)
        items = [VendorOut.model_validate(row.Vendor) for row in rows]
    return Page[VendorOut](items=items, total=total)


def list_products(vendor_id: int | None, limit: int, offset: int) -> Page[ProductOut]:
    if vendor_id is not None and not 1 <= vendor_id <= MAX_BIGINT:
        return Page[ProductOut](items=[], total=0)
    query = select(Product).order_by(Product.updated_at.desc(), Product.id.desc())
    if vendor_id is not None:
        query = query.where(Product.vendor_id == vendor_id)
    with get_sessionmaker()() as session:
        rows, total = _page(session, query, limit, offset)
        items = [ProductOut.model_validate(row.Product) for row in rows]
    return Page[ProductOut](items=items, total=total)


def list_alerts(limit: int, offset: int) -> Page[AlertListItemOut]:
    """Every alert whatever its status, with its import summary (no status filter)."""
    query = (
        select(
            Alert,
            Import.status.label("import_status"),
            Import.failure_code,
            Import.filename,
            Vendor.display_name.label("vendor_display_name"),
        )
        .join(Import, Import.id == Alert.import_id)
        .join(Vendor, Vendor.id == Import.vendor_id)
        .order_by(Alert.created_at.desc(), Alert.id.desc())
    )
    with get_sessionmaker()() as session:
        rows, total = _page(session, query, limit, offset)
        items = [
            AlertListItemOut.model_validate(
                {
                    "id": row.Alert.id,
                    "status": row.Alert.status,
                    "reason": row.Alert.reason,
                    "claimed_at": row.Alert.claimed_at,
                    "created_at": row.Alert.created_at,
                    "updated_at": row.Alert.updated_at,
                    "import_id": row.Alert.import_id,
                    "import_status": row.import_status,
                    "failure_code": row.failure_code,
                    "vendor_display_name": row.vendor_display_name,
                    "filename": row.filename,
                }
            )
            for row in rows
        ]
    return Page[AlertListItemOut](items=items, total=total)
