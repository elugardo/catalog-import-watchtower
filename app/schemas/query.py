"""Query parameters of the four list endpoints (spec section 7, `_docs/api.md`).

A query integer is an optional `-` followed by ASCII digits `0-9` only
(leading zeros allowed). Pydantic's lax `int` would also take `5.0`, `+5`,
` 5` and `1_0`, so the raw string is checked first and only then converted.
Range checks (the `Interval`, which also gives the generated schema its
`minimum` / `maximum`) run after the grammar. Every failure
is a `RequestValidationError` located in `query`, which `app.main` answers
with 400 `INVALID_QUERY` and the rule from `QUERY_RULES`.

A value with more than 19 significant digits is beyond the `BIGINT` range
whatever it is, so it is read as 2**63 (with its sign) instead of being
converted digit by digit: an `offset` that large is past the end of any list,
a `vendor_id` that large names no vendor, and a `limit` that large is still
out of range.
"""

import re
from typing import Annotated

from annotated_types import Interval
from fastapi import Query
from pydantic import BeforeValidator

MAX_LIMIT = 100
DEFAULT_LIMIT = 50
# The largest BIGINT; ids and offsets beyond it cannot match a row.
MAX_BIGINT = 2**63 - 1

_INTEGER = re.compile(r"-?[0-9]+")
_MAX_DIGITS = 19

# The `message` of the 400 for each parameter; it always names the parameter.
QUERY_RULES = {
    "limit": f"limit must be an integer between 1 and {MAX_LIMIT}",
    "offset": "offset must be an integer of at least 0",
    "vendor_id": "vendor_id must be an integer",
}


def parse_query_integer(value: object) -> object:
    """The raw query string as an int, or `ValueError` when it breaks the grammar."""
    if not isinstance(value, str):
        return value
    if not _INTEGER.fullmatch(value):
        raise ValueError("must be an optional '-' followed by the digits 0-9")
    negative = value.startswith("-")
    digits = value.removeprefix("-").lstrip("0") or "0"
    magnitude = 2**63 if len(digits) > _MAX_DIGITS else int(digits)
    return -magnitude if negative else magnitude


_GRAMMAR = BeforeValidator(parse_query_integer)

Limit = Annotated[int, Interval(ge=1, le=MAX_LIMIT), _GRAMMAR, Query(description="Page size.")]
Offset = Annotated[int, Interval(ge=0), _GRAMMAR, Query(description="Number of records to skip.")]
VendorId = Annotated[
    int | None,
    _GRAMMAR,
    Query(description="Only this vendor's products; all vendors when omitted."),
]
