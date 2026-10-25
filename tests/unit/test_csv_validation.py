"""`app.services.csv_validation`: module contract, parsing, headers and file-level rules.

Field rules, duplicates, ordering and the 1 000 cap are in
`test_csv_validation_fields.py`; the committed fixtures in
`test_csv_validation_fixtures.py`. Every call goes through `run()`, which
also checks the invariants that hold for every result.
"""

import ast
from pathlib import Path

import pytest

from app.schemas import ValidationErrorOut
from app.services import csv_validation
from app.services.csv_validation import CsvValidationResult, validate_csv

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
HEADER = "sku,name,price,quantity"
ROW_1 = "CHAIR-001,Oak Dining Chair,149.99,8"
ROW_2 = "TABLE-002,Round Dining Table,499.00,3"
ROW_3 = "LAMP-003,Desk Lamp,39.50,12"


def check(result: CsvValidationResult) -> CsvValidationResult:
    """Invariants of every result (module contract criteria)."""
    assert result.error_count == len(result.errors) <= 1000
    if result.errors:
        assert result.rows == []
    else:
        assert len(result.rows) == result.row_count
    for error in result.errors:
        assert set(error) == {"line", "column", "message"}
        assert ValidationErrorOut.model_validate(error).model_dump() == error
        assert len(error["message"]) <= 200
    for row in result.rows:
        assert set(row) == {"sku", "normalized_sku", "name", "price_cents", "quantity"}
        assert type(row["price_cents"]) is int
        assert type(row["quantity"]) is int
        assert row["normalized_sku"] == row["sku"].casefold()
    return result


def run(data: bytes | str) -> CsvValidationResult:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return check(validate_csv(data))


def csv_text(*lines: str, newline: str = "\n") -> str:
    return newline.join(lines) + newline


def only_error(result: CsvValidationResult) -> dict:
    assert result.error_count == 1, result.errors
    return result.errors[0]


def where(result: CsvValidationResult) -> list[tuple[int, str]]:
    return [(error["line"], error["column"]) for error in result.errors]


# --- module contract -------------------------------------------------------


def test_module_imports_nothing_from_db_http_or_app_layers():
    source = Path(csv_validation.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = ("sqlalchemy", "fastapi", "app.db", "app.models", "app.routers", "logging")
    for name in imported:
        assert not any(name == bad or name.startswith(bad + ".") for bad in forbidden), name
    assert imported  # the walk saw the imports at all


def test_valid_file_returns_normalised_rows_in_file_order():
    result = run(csv_text(HEADER, " Chair-001 , Oak Dining Chair ,149.99,8", ROW_2, ROW_3))
    assert result.errors == []
    assert result.error_count == 0
    assert result.row_count == 3
    assert result.rows[0] == {
        "sku": "Chair-001",
        "normalized_sku": "chair-001",
        "name": "Oak Dining Chair",
        "price_cents": 14999,
        "quantity": 8,
    }
    assert [row["sku"] for row in result.rows] == ["Chair-001", "TABLE-002", "LAMP-003"]


def test_trimming_is_str_strip():
    # U+3000 (ideographic space) and a tab are whitespace for str.strip().
    result = run(csv_text(HEADER, "　CHAIR-001\t,\tOak Chair　,1,2"))
    assert result.rows[0]["sku"] == "CHAIR-001"
    assert result.rows[0]["name"] == "Oak Chair"


def test_message_is_bounded_even_for_a_long_bad_value():
    bad = "X" * 150 + "!" + "Y" * 149
    result = run(csv_text(HEADER, f"{bad},Oak Chair,{bad},{bad}"))
    assert [error["column"] for error in result.errors] == ["sku", "price", "quantity"]
    for error in result.errors:
        assert len(error["message"]) <= 200
        assert "X" * 10 in error["message"]  # quotes a shortened own value


def test_header_message_is_bounded_with_many_long_unexpected_headers():
    extra = [f"unexpected_column_number_{index:02d}" for index in range(12)]
    result = run(csv_text(",".join([HEADER, *extra]), ROW_1))
    error = only_error(result)
    assert error["column"] == "header"
    assert error["message"].startswith("invalid header: unexpected 'unexpected_column_number_00'")
    assert len(error["message"]) == 200  # cut at the bound, not left long


def test_message_holds_nothing_from_other_rows():
    result = run(csv_text(HEADER, ROW_1, "BAD SKU,Mystery Item,1,1"))
    message = only_error(result)["message"]
    assert "BAD SKU" in message
    assert "CHAIR-001" not in message and "Mystery Item" not in message


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"\xe9", id="not-utf8"),
        pytest.param(b"\xef\xbb\xbf\xff\xfe", id="bom-then-not-utf8"),
    ],
)
def test_non_utf8_is_one_file_error(data):
    result = run(data)
    error = only_error(result)
    assert (error["line"], error["column"]) == (1, "file")
    assert result.row_count == 0


def test_nul_byte_in_name_is_a_name_error():
    result = run(csv_text(HEADER, "CHAIR-001,Oak\x00Chair,1,2"))
    assert where(result) == [(2, "name")]


@pytest.mark.parametrize(
    "lines",
    [
        pytest.param([HEADER, 'CHAIR-001,"Oak Chair,1,2', ROW_2], id="swallows-rest"),
        pytest.param([HEADER, ROW_1, 'TABLE-002,Table,1,"3'], id="last-field-open"),
    ],
)
def test_unterminated_quote_is_a_row_error_at_its_start_line(lines):
    result = run(csv_text(*lines))
    start = next(n for n, line in enumerate(lines, start=1) if line.count('"') == 1)
    assert where(result) == [(start, "row")]
    assert "never closed" in result.errors[0]["message"]


def test_unterminated_quote_in_header_is_a_header_error():
    result = run(csv_text('sku,"name,price,quantity', ROW_1))
    assert where(result) == [(1, "header")]


def test_field_over_the_csv_size_limit_is_a_row_error():
    huge = "x" * 131_073
    result = run(csv_text(HEADER, ROW_1, f'TABLE-002,"{huge}",1,2', ROW_3))
    assert where(result) == [(3, "row")]
    assert "field limit" in result.errors[0]["message"]


# --- row_count ---------------------------------------------------------------


def test_row_count_counts_a_multiline_record_once():
    result = run(csv_text(HEADER, 'CHAIR-001,"Oak', 'Chair",1,2', ROW_2))
    assert result.row_count == 2


def test_row_count_is_counted_under_an_invalid_header():
    result = run(csv_text("sku,name,price", *[ROW_1] * 600))
    assert where(result) == [(1, "header")]
    assert result.row_count == 600


@pytest.mark.parametrize("data", ["", HEADER + "\n"], ids=["empty", "header-only"])
def test_row_count_is_zero_without_data_rows(data):
    assert run(data).row_count == 0


# --- parsing: BOM, line endings, quoting, delimiter, empty lines ---------------


def test_leading_bom_is_stripped():
    plain = (FIXTURES / "valid.csv").read_bytes()
    with_bom = run(b"\xef\xbb\xbf" + plain)
    assert with_bom.rows == run(plain).rows
    assert with_bom.rows and with_bom.rows[0]["sku"] == "CHAIR-001"


def test_bom_header_would_be_unexpected_if_not_stripped():
    # The stripped BOM is the reason `sku` is found: a second BOM is content.
    result = run(b"\xef\xbb\xbf\xef\xbb\xbf" + csv_text(HEADER, ROW_1).encode())
    error = only_error(result)
    assert error["column"] == "header"
    assert "missing sku" in error["message"]


def test_bom_inside_a_sku_is_a_sku_error():
    result = run(csv_text(HEADER, "﻿CHAIR-001,Oak Chair,1,2"))
    assert where(result) == [(2, "sku")]


@pytest.mark.parametrize(
    "newline_pattern",
    [["\n"] * 4, ["\r\n"] * 4, ["\r\n", "\n", "\r\n", "\n"]],
    ids=["lf", "crlf", "mixed"],
)
def test_line_endings_give_identical_rows_and_error_lines(newline_pattern):
    good = [HEADER, ROW_1, ROW_2, ROW_3]
    bad = [HEADER, ROW_1, "TABLE-002,Round Dining Table,499.00,-3", ROW_3]

    def join(lines: list[str]) -> str:
        return "".join(line + nl for line, nl in zip(lines, newline_pattern, strict=True))

    assert run(join(good)).rows == run(csv_text(*good)).rows
    assert where(run(join(bad))) == [(3, "quantity")]


def test_quoted_name_with_comma_and_escaped_quote():
    result = run(
        csv_text(HEADER, 'CHAIR-001,"Chair, oak",1,2', 'TABLE-002,"The ""Big"" Table",1,2')
    )
    assert [row["name"] for row in result.rows] == ["Chair, oak", 'The "Big" Table']


def test_quoted_header_is_accepted():
    result = run(csv_text('"sku","name","price","quantity"', ROW_1))
    assert result.errors == [] and len(result.rows) == 1


def test_multiline_record_reports_its_start_line_and_next_line_is_physical():
    result = run(csv_text(HEADER, 'CHAIR-001,"Oak', 'Chair",1,2', "TABLE-002,Table,1,-1"))
    assert where(result) == [(2, "name"), (4, "quantity")]


def test_semicolon_delimiter_is_one_header_error_naming_the_header_found():
    result = run((FIXTURES / "semicolon.csv").read_bytes())
    error = only_error(result)
    assert (error["line"], error["column"]) == (1, "header")
    assert "sku;name;price;quantity" in error["message"]


def test_empty_lines_are_ignored_and_do_not_shift_line_numbers():
    result = run(csv_text("", "", HEADER, ROW_1, "", "", "", "TABLE-002,Table,1,-1", "", ""))
    assert result.row_count == 2
    assert where(result) == [(8, "quantity")]


def test_error_after_an_empty_line_three_reports_line_four():
    result = run(csv_text(HEADER, ROW_1, "", "TABLE-002,Table,1,-1"))
    assert where(result) == [(4, "quantity")]


def test_header_after_two_empty_lines_reports_its_physical_line():
    result = run(csv_text("", "", "sku,name,price", ROW_1))
    assert where(result) == [(3, "header")]


def test_header_after_empty_lines_is_found_and_rows_parse():
    result = run(csv_text("", "", HEADER, ROW_1))
    assert result.errors == [] and result.rows[0]["sku"] == "CHAIR-001"


def test_line_of_spaces_is_a_data_row_with_a_field_count_error():
    result = run(csv_text(HEADER, ROW_1, "   "))
    assert where(result) == [(3, "row")]
    assert result.row_count == 2


def test_line_of_commas_is_a_data_row_with_four_blank_errors():
    result = run(csv_text(HEADER, ROW_1, ",,,"))
    assert where(result) == [(3, "sku"), (3, "name"), (3, "price"), (3, "quantity")]


# --- headers -------------------------------------------------------------------


def test_headers_are_trimmed_and_case_insensitive():
    result = run(csv_text("SKU, Name ,PRICE,quantity", ROW_1))
    assert result.errors == [] and result.rows[0]["price_cents"] == 14999


def test_headers_in_any_order_map_values_to_the_right_field():
    result = run(csv_text("quantity,price,name,sku", "8,149.99,Oak Dining Chair,CHAIR-001"))
    assert result.rows == [
        {
            "sku": "CHAIR-001",
            "normalized_sku": "chair-001",
            "name": "Oak Dining Chair",
            "price_cents": 14999,
            "quantity": 8,
        }
    ]


def test_row_error_column_is_canonical_even_with_a_cased_header():
    result = run(csv_text("sku,name, Price ,QUANTITY", "CHAIR-001,Oak,1.999,x"))
    assert where(result) == [(2, "price"), (2, "quantity")]


@pytest.mark.parametrize(
    ("header", "expected_in_message"),
    [
        pytest.param("sku,name,price", ["quantity"], id="missing"),
        pytest.param("sku,name,price,quantity,color", ["color"], id="unexpected"),
        pytest.param("sku,name,price,quantity,Price", ["duplicate", "price"], id="duplicate-price"),
        pytest.param("sku,SKU,name,price,quantity", ["duplicate", "sku"], id="duplicate-sku"),
        pytest.param("sku,name,price,quantity,", ["empty"], id="trailing-comma"),
        pytest.param("name,price,colour,size", ["sku", "quantity", "colour", "size"], id="several"),
    ],
)
def test_invalid_header_is_one_error_naming_every_offending_header(header, expected_in_message):
    result = run(csv_text(header, "CHAIR-001,Oak Dining Chair,149.99,8,x", "BAD SKU,,,", "   "))
    error = only_error(result)
    assert (error["line"], error["column"]) == (1, "header")
    for text in expected_in_message:
        assert text in error["message"].casefold()


def test_invalid_header_takes_precedence_over_the_row_limit():
    result = run(csv_text("sku,name,price", *["CHAIR-001,Oak,1"] * 501))
    assert where(result) == [(1, "header")]
    assert result.row_count == 501


def test_invalid_header_only_file_gives_the_header_error():
    result = run(csv_text("sku,name,price"))
    assert where(result) == [(1, "header")]


# --- field count ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "actual"),
    [("CHAIR-001,Oak Dining Chair,149.99", 3), ("CHAIR-001,Oak Dining Chair,149.99,8,extra", 5)],
    ids=["fewer", "more"],
)
def test_field_count_mismatch_is_one_row_error(row, actual):
    result = run(csv_text(HEADER, row, ROW_2))
    error = only_error(result)
    assert (error["line"], error["column"]) == (2, "row")
    assert "4" in error["message"] and str(actual) in error["message"]


def test_field_count_row_is_left_out_of_the_duplicate_check():
    result = run(csv_text(HEADER, ROW_1, "CHAIR-001,Oak Dining Chair,149.99"))
    assert where(result) == [(3, "row")]


# --- empty and header-only files, row limit ------------------------------------------


@pytest.mark.parametrize(
    "data",
    [b"", b"\xef\xbb\xbf", b"\n\n\r\n\n"],
    ids=["zero-bytes", "bom-only", "empty-lines-only"],
)
def test_empty_file_is_one_file_error(data):
    result = run(data)
    error = only_error(result)
    assert (error["line"], error["column"]) == (1, "file")
    assert "at least one data row" in error["message"]
    assert result.row_count == 0


@pytest.mark.parametrize(
    "data",
    [HEADER, HEADER + "\n", HEADER + "\r\n\r\n\n", "\n" + HEADER + "\n\n"],
    ids=["no-newline", "newline", "trailing-empty-lines", "leading-empty-line"],
)
def test_header_only_is_one_file_error_on_line_one(data):
    result = run(data)
    error = only_error(result)
    assert (error["line"], error["column"]) == (1, "file")
    assert "at least one data row" in error["message"]


def _rows(count: int, bad_every: int = 0) -> list[str]:
    rows = []
    for index in range(count):
        quantity = "-1" if bad_every and index % bad_every == 0 else "1"
        rows.append(f"SKU-{index:04d},Item {index},1.00,{quantity}")
    return rows


def test_500_rows_pass():
    result = run(csv_text(HEADER, *_rows(500)))
    assert result.errors == [] and len(result.rows) == 500


def test_500_rows_plus_20_empty_lines_pass():
    lines = _rows(500)
    result = run(csv_text(HEADER, *lines[:250], *[""] * 20, *lines[250:]))
    assert result.errors == [] and result.row_count == 500


def test_501_rows_is_one_file_error():
    result = run(csv_text(HEADER, *_rows(501)))
    assert result.errors == [
        {"line": 1, "column": "file", "message": "file has 501 data rows, limit 500"}
    ]
    assert result.row_count == 501


def test_501_rows_with_invalid_rows_reports_only_the_limit():
    result = run(csv_text(HEADER, *_rows(501, bad_every=7)))
    assert where(result) == [(1, "file")]
    assert result.errors[0]["message"] == "file has 501 data rows, limit 500"
