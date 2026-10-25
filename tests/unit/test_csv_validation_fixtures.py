"""The committed CSV fixtures: exact bytes (spec section 9 scenarios 1 to 3) and what they validate to.

The byte assertions also prove that `.gitattributes` (`fixtures/*.csv -text`)
keeps git from converting line endings on a `core.autocrlf=true` checkout.
"""

from pathlib import Path

from tests.unit.test_csv_validation import FIXTURES, run, where

REPO_ROOT = Path(__file__).resolve().parents[2]


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def prices_and_quantities(result) -> list[tuple[str, int, int]]:
    return [(row["sku"], row["price_cents"], row["quantity"]) for row in result.rows]


def test_valid_csv_is_the_spec_example_byte_for_byte():
    assert read("valid.csv") == (
        b"sku,name,price,quantity\n"
        b"CHAIR-001,Oak Dining Chair,149.99,8\n"
        b"TABLE-002,Round Dining Table,499.00,3\n"
        b"LAMP-003,Desk Lamp,39.50,12\n"
    )
    assert b"\r" not in read("valid.csv")


def test_valid_csv_validates_to_three_rows():
    result = run(read("valid.csv"))
    assert prices_and_quantities(result) == [
        ("CHAIR-001", 14999, 8),
        ("TABLE-002", 49900, 3),
        ("LAMP-003", 3950, 12),
    ]
    assert result.row_count == 3


def test_update_csv_is_only_chair_001():
    assert read("update.csv") == b"sku,name,price,quantity\nCHAIR-001,Oak Dining Chair,129.99,20\n"
    assert prices_and_quantities(run(read("update.csv"))) == [("CHAIR-001", 12999, 20)]


def test_invalid_csv_is_exact_and_fails_on_line_4_quantity():
    assert read("invalid.csv") == (
        b"sku,name,price,quantity\n"
        b"CHAIR-001,Oak Dining Chair,99.99,1\n"
        b"STOOL-004,Bar Stool,79.00,6\n"
        b"TABLE-002,Round Dining Table,499.00,-2\n"
        b"LAMP-003,Desk Lamp,39.50,12\n"
    )
    result = run(read("invalid.csv"))
    assert where(result) == [(4, "quantity")]
    assert "'-2'" in result.errors[0]["message"]
    assert result.error_count == 1
    assert result.row_count == 4
    assert result.rows == []


def test_crlf_fixture_keeps_its_crlf_bytes_and_matches_valid():
    data = read("crlf.csv")
    assert b"\r\n" in data
    assert data.replace(b"\r\n", b"\n") == read("valid.csv")
    assert run(data).rows == run(read("valid.csv")).rows


def test_bom_fixture_starts_with_a_bom_and_matches_valid():
    data = read("bom.csv")
    assert data == b"\xef\xbb\xbf" + read("valid.csv")
    assert run(data).rows == run(read("valid.csv")).rows


def test_header_only_fixture():
    result = run(read("header-only.csv"))
    assert where(result) == [(1, "file")]
    assert "at least one data row" in result.errors[0]["message"]


def test_duplicate_sku_case_fixture():
    assert where(run(read("duplicate-sku-case.csv"))) == [(2, "sku"), (5, "sku")]


def test_empty_lines_fixture_keeps_physical_line_numbers():
    result = run(read("empty-lines.csv"))
    assert where(result) == [(7, "quantity")]
    assert result.row_count == 3


def test_fixtures_hold_no_vendor_column():
    for path in FIXTURES.glob("*.csv"):
        header = path.read_bytes().lstrip(b"\xef\xbb\xbf").splitlines()[0].lower()
        assert b"vendor" not in header, path.name


def test_gitattributes_turns_off_eol_conversion_for_fixtures():
    lines = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "fixtures/*.csv -text" in lines
