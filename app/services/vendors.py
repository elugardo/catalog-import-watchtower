"""Vendor find-or-create (spec section 4 F1, F2).

A vendor is matched by `normalized_name`, the `casefold()` of the trimmed
display name (so `Straße` and `STRASSE` are one vendor, and inner whitespace
is significant). The first spelling seen becomes `display_name` and is never
overwritten by a later upload.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Vendor


def normalize_vendor_name(display_name: str) -> str:
    return display_name.strip().casefold()


def find_or_create_vendor(session: Session, display_name: str) -> Vendor:
    """The vendor for this name, created if new. Safe under concurrent first uploads.

    `INSERT ... ON CONFLICT (normalized_name) DO NOTHING` followed by a select:
    a second transaction inserting the same name waits on the unique index,
    then does nothing and selects the row the first one committed.
    """
    display_name = display_name.strip()
    normalized = normalize_vendor_name(display_name)
    session.execute(
        insert(Vendor)
        .values(display_name=display_name, normalized_name=normalized)
        .on_conflict_do_nothing(index_elements=[Vendor.normalized_name])
    )
    return session.execute(select(Vendor).where(Vendor.normalized_name == normalized)).scalar_one()
