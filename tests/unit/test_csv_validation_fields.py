"""`app.services.csv_validation`: field rules, duplicates, error order and the 1 000 cap."""

import pytest

from tests.unit.test_csv_validation import HEADER, csv_text, run, where

GOOD = {"sku": "CHAIR-001", "name": "Oak Dining Chair", "price": "149.99", "quantity": "8"}


def row_with(**overrides: str) -> str:
    """One data line in `HEADER` order, with some fields replaced."""
    values = {**GOOD, **overrides}
    return ",".join(values[column] for column in HEADER.split(","))


def validate_one(**overrides: str):
    return run(csv_text(HEADER, row_with(**overrides)))


def assert_one_error(result, column: str, line: int = 2) -> dict:
    assert where(result) == [(line, column)], result.errors
    return result.errors[0]


# --- blank -----------------------------------------------------------------------


@pytest.mark.parametrize("column", ["sku", "name", "price", "quantity"])
@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
def test_blank_field_is_an_error(column, blank):
    error = assert_one_error(validate_one(**{column: blank}), column)
    assert "blank" in error["message"]


def test_all_four_blank_gives_four_errors():
    result = validate_one(sku=" ", name="", price="  ", quantity="")
    assert where(result) == [(2, "sku"), (2, "name"), (2, "price"), (2, "quantity")]


# --- sku -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" CHAIR-001 ", "CHAIR-001"),
        ("chair_01-A", "chair_01-A"),
        ("A" * 64, "A" * 64),
        ("  " + "A" * 64 + "  ", "A" * 64),
    ],
    ids=["padded", "underscore-dash", "64-chars", "64-chars-padded"],
)
def test_sku_passes(value, expected):
    result = validate_one(sku=value)
    assert result.rows[0]["sku"] == expected


@pytest.mark.parametrize(
    "value",
    ["CHAIR 001", "CHAIR.001", "CHAIR/001", "CHÄIR-001", "ＣHAIR", "A" * 65],
    ids=["space", "dot", "slash", "non-ascii-letter", "full-width", "65-chars"],
)
def test_sku_error(value):
    assert_one_error(validate_one(sku=value), "sku")


# --- name -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["Café Chair", "N" * 120, "é" * 120],
    ids=["accent", "120-chars", "120-e-acute-240-bytes"],
)
def test_name_passes(value):
    assert validate_one(name=value).rows[0]["name"] == value


@pytest.mark.parametrize(
    "value",
    ["N" * 121, "Oak\tChair", "Oak\x00Chair", "Oak\x07Chair", "Oak\x7fChair", '"Oak\nChair"'],
    ids=["121-chars", "tab", "nul", "bell", "del", "line-break"],
)
def test_name_error(value):
    assert_one_error(validate_one(name=value), "name")


# --- price -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "cents"),
    [
        ("149.99", 14999),
        ("149.9", 14990),
        ("149", 14900),
        ("0", 0),
        ("0.00", 0),
        ("0.5", 50),
        ("0.29", 30),
        ("1.10", 110),
        ("0149.99", 14999),
        (" 39.50 ", 3950),
        ("9999999999.99", 999999999999),
    ],
)
def test_price_passes_as_integer_cents(value, cents):
    row = validate_one(price=value).rows[0]
    assert row["price_cents"] == cents
    assert type(row["price_cents"]) is int


@pytest.mark.parametrize(
    "value",
    [
        "149.999",
        "$149.99",
        "149.99$",
        '"1,499.99"',
        "1 499.99",
        "-1",
        "+5",
        "1e3",
        ".5",
        "5.",
        "12345678901",
        "NaN",
        "١٤٩",
    ],
)
def test_price_error(value):
    assert_one_error(validate_one(price=value), "price")


# --- quantity ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0", 0), ("8", 8), ("08", 8), ("999999999", 999999999)],
)
def test_quantity_passes(value, expected):
    row = validate_one(quantity=value).rows[0]
    assert row["quantity"] == expected
    assert type(row["quantity"]) is int


@pytest.mark.parametrize(
    "value",
    ["-2", "+2", "1.0", "1e3", "8 pcs", '"1,000"', "1234567890", "٨"],
)
def test_quantity_error(value):
    assert_one_error(validate_one(quantity=value), "quantity")


def test_all_four_bad_gives_four_errors_in_header_order():
    result = validate_one(sku="CHAIR 001", name="N" * 121, price="1.999", quantity="-1")
    assert where(result) == [(2, "sku"), (2, "name"), (2, "price"), (2, "quantity")]


# --- duplicates ---------------------------------------------------------------------------


def test_duplicate_skus_differing_in_case_error_on_both_lines():
    result = run(
        csv_text(
            HEADER,
            row_with(sku="CHAIR-001"),
            row_with(sku="TABLE-002"),
            row_with(sku="LAMP-003"),
            row_with(sku="chair-001"),
        )
    )
    assert where(result) == [(2, "sku"), (5, "sku")]
    assert "'CHAIR-001'" in result.errors[0]["message"]
    assert "'chair-001'" in result.errors[1]["message"]
    assert "chair-001" not in result.errors[0]["message"]  # nothing from the other row
    assert result.rows == []


def test_sku_three_times_gives_three_errors():
    result = run(csv_text(HEADER, row_with(sku="A-1"), row_with(sku="a-1"), row_with(sku="A-1")))
    assert where(result) == [(2, "sku"), (3, "sku"), (4, "sku")]


def test_two_different_duplicated_skus_give_four_errors():
    skus = ["A-1", "B-2", "a-1", "b-2"]
    result = run(csv_text(HEADER, *[row_with(sku=sku) for sku in skus]))
    assert where(result) == [(2, "sku"), (3, "sku"), (4, "sku"), (5, "sku")]


@pytest.mark.parametrize("sku", ["", "CHAIR 001"], ids=["blank", "invalid"])
def test_invalid_skus_are_not_duplicates(sku):
    result = run(csv_text(HEADER, row_with(sku=sku), row_with(sku=sku)))
    assert where(result) == [(2, "sku"), (3, "sku")]
    assert all("duplicate" not in error["message"] for error in result.errors)


def test_duplicate_on_a_row_with_other_errors_keeps_header_order():
    result = run(csv_text("quantity,sku,name,price", "-1,A-1,Oak,1", "1,a-1,Oak,1.999"))
    assert where(result) == [(2, "quantity"), (2, "sku"), (3, "sku"), (3, "price")]


# --- ordering and the cap ------------------------------------------------------------------


def test_errors_follow_the_file_header_order():
    result = run(csv_text("quantity,price,name,sku", "-1,1.999,,CHAIR 001"))
    assert where(result) == [(2, "quantity"), (2, "price"), (2, "name"), (2, "sku")]


def test_errors_are_sorted_by_line_with_row_errors_standing_alone():
    lines = [row_with(quantity="-1"), "only,three,fields", row_with(sku="B-2", price="x")]
    result = run(csv_text(HEADER, *lines))
    assert where(result) == [(2, "quantity"), (3, "row"), (4, "price")]


def test_below_the_cap_every_error_is_returned():
    lines = [row_with(sku=f"S-{index}", quantity="-1") for index in range(30)]
    result = run(csv_text(HEADER, *lines))
    assert result.error_count == 30
    assert [line for line, _ in where(result)] == list(range(2, 32))


def test_the_cap_stops_at_1000_errors():
    bad_row = row_with(sku="BAD SKU", name="", price="1.999", quantity="-1")
    result = run(csv_text(HEADER, *[bad_row] * 500))
    assert result.error_count == 1000
    assert len(result.errors) == 1000
    assert result.row_count == 500
    lines = [line for line, _ in where(result)]
    assert lines[0] == 2 and lines[-1] == 251
    assert sorted(set(lines)) == list(range(2, 252))
    columns = ["sku", "name", "price", "quantity"]
    assert where(result)[:20] == [(line, column) for line in range(2, 7) for column in columns]
