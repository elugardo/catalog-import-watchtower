"""Pure CSV parsing and validation (spec section 4 F1 row limit and F2).

`validate_csv(data)` turns the raw upload bytes into either normalised rows or
an ordered list of `{line, column, message}` errors. It touches no database,
no HTTP layer and no logger, and it never raises: every problem with the
input comes back as an error.

Error `column` values:

- `sku`, `name`, `price`, `quantity`: a field rule failed on that row;
- `header`: the header row is invalid (missing, unexpected, duplicate or
  empty headers); it is then the only error;
- `row`: the record as a whole is wrong (field count differs from the
  header, an unterminated quoted field, a field over the `csv` size limit);
- `file`: the file as a whole is wrong (not UTF-8, no data rows, more than
  500 data rows); always on line 1.

`line` is the physical file line on which the record starts (the header is
line 1 unless empty lines precede it). Errors are ordered by line, then by
the file's header column order, and collection stops at 1 000.
"""

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TypedDict

MAX_DATA_ROWS = 500
MAX_ERRORS = 1000
MAX_MESSAGE_LENGTH = 200
MAX_QUOTED_VALUE_LENGTH = 40
MAX_NAME_LENGTH = 120
MAX_DUPLICATE_LINES_SHOWN = 5

REQUIRED_HEADERS = ("sku", "name", "price", "quantity")

_UTF8_BOM = b"\xef\xbb\xbf"
# Explicit ASCII classes: `\d` would also accept Arabic-Indic and other digits.
_SKU_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_PRICE_RE = re.compile(r"[0-9]{1,10}(?:\.[0-9]{1,2})?")
_QUANTITY_RE = re.compile(r"[0-9]{1,9}")


class ValidationErrorDict(TypedDict):
    line: int
    column: str
    message: str


class ProductRow(TypedDict):
    sku: str
    normalized_sku: str
    name: str
    price_cents: int
    quantity: int


@dataclass(frozen=True)
class CsvValidationResult:
    """`rows` is empty whenever `errors` is not; `error_count == len(errors)`."""

    rows: list[ProductRow] = field(default_factory=list)
    errors: list[ValidationErrorDict] = field(default_factory=list)
    error_count: int = 0
    row_count: int = 0


@dataclass
class _Record:
    line: int
    fields: list[str] | None  # None when the record could not be parsed
    problem: str | None = None


class _Lines:
    """Line source for `csv.reader` that remembers whether it ran dry.

    The default (non-strict) dialect silently closes a quoted field that is
    still open at end of input. The reader only asks for another line in the
    middle of a record when it is inside a quoted field, so a record returned
    after the source ran dry is an unterminated quote.
    """

    def __init__(self, text: str) -> None:
        self._lines = iter(io.StringIO(text, newline=""))
        self.exhausted = False

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        try:
            return next(self._lines)
        except StopIteration:
            self.exhausted = True
            raise


def validate_csv(data: bytes) -> CsvValidationResult:
    """Validate a whole catalog CSV; see the module docstring for the contract."""
    data = data.removeprefix(_UTF8_BOM)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _failure([_error(1, "file", "file is not valid UTF-8")], row_count=0)

    records = _read_records(text)
    if not records:
        return _failure([_no_data_rows()], row_count=0)

    header, data_records = records[0], records[1:]
    row_count = len(data_records)

    header_problem = _header_problem(header)
    if header_problem is not None:
        return _failure([_error(header.line, "header", header_problem)], row_count)
    assert header.fields is not None  # a header that failed to parse has a problem
    columns = [_header_key(cell) for cell in header.fields]

    if row_count == 0:
        return _failure([_no_data_rows()], row_count)
    if row_count > MAX_DATA_ROWS:
        message = f"file has {row_count} data rows, limit {MAX_DATA_ROWS}"
        return _failure([_error(1, "file", message)], row_count)

    return _validate_rows(columns, data_records)


def _read_records(text: str) -> list[_Record]:
    """Every non-empty record with its starting line; stops at the first unparseable one."""
    lines = _Lines(text)
    reader = csv.reader(lines)
    records: list[_Record] = []
    while True:
        start = reader.line_num + 1
        try:
            fields = next(reader)
        except StopIteration:
            return records
        except csv.Error as exc:
            records.append(_Record(start, None, f"record could not be parsed: {exc}"))
            return records
        if lines.exhausted:
            records.append(_Record(start, None, "a quoted field is never closed"))
            return records
        if fields:  # a completely empty line comes back as []
            records.append(_Record(start, fields))


def _header_key(cell: str) -> str:
    """Trimmed, case-insensitive header name; ASCII only, so `ſku` or a Kelvin sign never match `sku`."""
    name = cell.strip()
    return name.lower() if name.isascii() else name


def _header_problem(header: _Record) -> str | None:
    if header.fields is None:
        return f"invalid header: {header.problem}"
    seen: dict[str, int] = {}
    unexpected: dict[str, str] = {}  # key -> first spelling seen
    empty_positions: list[int] = []
    for position, cell in enumerate(header.fields, start=1):
        name = cell.strip()
        key = _header_key(cell)
        if not name:
            empty_positions.append(position)
        elif key not in REQUIRED_HEADERS:
            unexpected.setdefault(key, name)
        seen[key] = seen.get(key, 0) + 1
    missing = [name for name in REQUIRED_HEADERS if name not in seen]
    duplicate = [name for name in REQUIRED_HEADERS if seen.get(name, 0) > 1]
    duplicate += [name for key, name in unexpected.items() if seen[key] > 1]

    parts = []
    if missing:
        parts.append("missing " + ", ".join(missing))
    if unexpected:
        parts.append("unexpected " + ", ".join(_quote(name) for name in unexpected.values()))
    if duplicate:
        parts.append("duplicate " + ", ".join(_quote(name) for name in duplicate))
    if empty_positions:
        parts.append("empty header in position " + ", ".join(map(str, empty_positions)))
    if not parts:
        return None
    return "invalid header: " + "; ".join(parts) + "; expected sku, name, price, quantity"


def _validate_rows(columns: list[str], records: list[_Record]) -> CsvValidationResult:
    # Pass 1: which format-valid SKUs repeat, so duplicates can be reported on
    # every occurrence, including the first, while errors stay in line order.
    sku_index = columns.index("sku")
    lines_by_sku: dict[str, list[int]] = {}
    for record in records:
        if record.fields is None or len(record.fields) != len(columns):
            continue
        sku = record.fields[sku_index].strip()
        if _SKU_RE.fullmatch(sku):
            lines_by_sku.setdefault(sku.casefold(), []).append(record.line)

    # Pass 2: errors in line order, then header order; stop at the cap.
    rows: list[ProductRow] = []
    errors: list[ValidationErrorDict] = []
    for record in records:
        for error in _record_errors(columns, record, lines_by_sku, rows):
            errors.append(error)
            if len(errors) == MAX_ERRORS:
                return _failure(errors, len(records))
    if errors:
        return _failure(errors, len(records))
    return CsvValidationResult(rows=rows, errors=[], error_count=0, row_count=len(records))


def _record_errors(
    columns: list[str],
    record: _Record,
    lines_by_sku: dict[str, list[int]],
    rows: list[ProductRow],
) -> Iterator[ValidationErrorDict]:
    if record.fields is None:
        yield _error(record.line, "row", record.problem or "record could not be parsed")
        return
    if len(record.fields) != len(columns):
        message = f"expected {len(columns)} fields, got {len(record.fields)}"
        yield _error(record.line, "row", message)
        return

    values = {column: cell.strip() for column, cell in zip(columns, record.fields, strict=True)}
    row_errors: list[ValidationErrorDict] = []
    for column in columns:
        problem = _FIELD_RULES[column](values[column])
        if problem is None and column == "sku":
            problem = _duplicate_problem(values["sku"], record.line, lines_by_sku)
        if problem is not None:
            row_errors.append(_error(record.line, column, problem))
    if row_errors:
        yield from row_errors
        return
    rows.append(
        ProductRow(
            sku=values["sku"],
            normalized_sku=values["sku"].casefold(),
            name=values["name"],
            price_cents=_price_cents(values["price"]),
            quantity=int(values["quantity"]),
        )
    )


def _sku_problem(value: str) -> str | None:
    if not value:
        return "must not be blank"
    if not _SKU_RE.fullmatch(value):
        return f"must be 1-64 characters of A-Z, a-z, 0-9, _ or -, got {_quote(value)}"
    return None


def _name_problem(value: str) -> str | None:
    if not value:
        return "must not be blank"
    if len(value) > MAX_NAME_LENGTH:
        return f"must be at most {MAX_NAME_LENGTH} characters, got {len(value)}"
    if not value.isprintable():
        return "must contain only printable characters"
    return None


def _price_problem(value: str) -> str | None:
    if not value:
        return "must not be blank"
    if not _PRICE_RE.fullmatch(value):
        return (
            "must be a plain amount with up to 10 digits and 2 decimals "
            f"(no sign, symbol or separator), got {_quote(value)}"
        )
    return None


def _quantity_problem(value: str) -> str | None:
    if not value:
        return "must not be blank"
    if not _QUANTITY_RE.fullmatch(value):
        return f"must be a whole number of up to 9 digits, got {_quote(value)}"
    return None


_FIELD_RULES = {
    "sku": _sku_problem,
    "name": _name_problem,
    "price": _price_problem,
    "quantity": _quantity_problem,
}


def _duplicate_problem(sku: str, line: int, lines_by_sku: dict[str, list[int]]) -> str | None:
    lines = lines_by_sku.get(sku.casefold(), [])
    if len(lines) < 2:
        return None
    others = [other for other in lines if other != line]
    shown = ", ".join(map(str, others[:MAX_DUPLICATE_LINES_SHOWN]))
    more = len(others) - MAX_DUPLICATE_LINES_SHOWN
    suffix = f" and {more} more" if more > 0 else ""
    return f"duplicate SKU {_quote(sku)}, also on line {shown}{suffix}"


def _price_cents(value: str) -> int:
    """Integer cents from a value that matched `_PRICE_RE`; no floating point."""
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))


def _quote(value: str) -> str:
    """The value in quotes, shortened, with control characters escaped."""
    if len(value) > MAX_QUOTED_VALUE_LENGTH:
        value = value[: MAX_QUOTED_VALUE_LENGTH - 3] + "..."
    printable = "".join(char if char.isprintable() else repr(char)[1:-1] for char in value)
    return f"'{printable}'"


def _error(line: int, column: str, message: str) -> ValidationErrorDict:
    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[: MAX_MESSAGE_LENGTH - 3] + "..."
    return ValidationErrorDict(line=line, column=column, message=message)


def _no_data_rows() -> ValidationErrorDict:
    return _error(1, "file", "file must contain at least one data row")


def _failure(errors: list[ValidationErrorDict], row_count: int) -> CsvValidationResult:
    return CsvValidationResult(rows=[], errors=errors, error_count=len(errors), row_count=row_count)
