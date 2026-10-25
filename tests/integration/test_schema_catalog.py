"""After `alembic upgrade head`, the PostgreSQL catalog shows the schema of spec section 6.

Column sets, types and nullability, BIGSERIAL ids, named constraints, and no
native enum types. The expectations are written out by hand from the spec and
the CIW-02 criteria, not derived from the models.
"""

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from tests.integration.conftest import REPO_ROOT

BIGINT = "bigint"
INT = "integer"
TEXT = "text"
VARCHAR = "character varying"
TSTZ = "timestamp with time zone"
NULL, NOT_NULL = True, False

# table -> column -> (data_type, nullable)
EXPECTED_COLUMNS = {
    "vendors": {
        "id": (BIGINT, NOT_NULL),
        "display_name": (TEXT, NOT_NULL),
        "normalized_name": (TEXT, NOT_NULL),
        "created_at": (TSTZ, NOT_NULL),
    },
    "products": {
        "id": (BIGINT, NOT_NULL),
        "vendor_id": (BIGINT, NOT_NULL),
        "sku": (VARCHAR, NOT_NULL),
        "normalized_sku": (VARCHAR, NOT_NULL),
        "name": (TEXT, NOT_NULL),
        "price_cents": (BIGINT, NOT_NULL),
        "quantity": (INT, NOT_NULL),
        "updated_at": (TSTZ, NOT_NULL),
    },
    "imports": {
        "id": (BIGINT, NOT_NULL),
        "vendor_id": (BIGINT, NOT_NULL),
        "filename": (TEXT, NOT_NULL),
        "csv_bytes": ("bytea", NOT_NULL),
        "sha256": (VARCHAR, NOT_NULL),
        "row_count": (INT, NOT_NULL),
        "product_count": (INT, NULL),
        "status": (VARCHAR, NOT_NULL),
        "failure_code": (VARCHAR, NULL),
        "validation_errors_json": ("jsonb", NOT_NULL),
        "validation_error_count": (INT, NOT_NULL),
        "inject_transient_failure": ("boolean", NOT_NULL),
        "created_at": (TSTZ, NOT_NULL),
        "completed_at": (TSTZ, NULL),
    },
    "import_attempts": {
        "id": (BIGINT, NOT_NULL),
        "import_id": (BIGINT, NOT_NULL),
        "attempt_number": (INT, NOT_NULL),
        "status": (VARCHAR, NOT_NULL),
        "error_code": (VARCHAR, NULL),
        "trace_id": (VARCHAR, NULL),
        "started_at": (TSTZ, NOT_NULL),
        "finished_at": (TSTZ, NULL),
    },
    "alerts": {
        "id": (BIGINT, NOT_NULL),
        "import_id": (BIGINT, NOT_NULL),
        "status": (VARCHAR, NOT_NULL),
        "reason": (TEXT, NOT_NULL),
        "claimed_at": (TSTZ, NULL),
        "created_at": (TSTZ, NOT_NULL),
        "updated_at": (TSTZ, NOT_NULL),
    },
    "agent_actions": {
        "id": (BIGINT, NOT_NULL),
        "alert_id": (BIGINT, NOT_NULL),
        "action": (VARCHAR, NOT_NULL),
        "reason_summary": (TEXT, NULL),
        "tool_name": (VARCHAR, NULL),
        "result": ("jsonb", NULL),
        "created_at": (TSTZ, NOT_NULL),
    },
}

# conname -> (contype, table, columns)
EXPECTED_CONSTRAINTS = {
    "uq_vendors_normalized_name": ("u", "vendors", ["normalized_name"]),
    "uq_products_vendor_id_normalized_sku": ("u", "products", ["vendor_id", "normalized_sku"]),
    "uq_import_attempts_import_id_attempt_number": (
        "u",
        "import_attempts",
        ["import_id", "attempt_number"],
    ),
    "uq_alerts_import_id": ("u", "alerts", ["import_id"]),
    "ck_imports_status": ("c", "imports", ["status"]),
    "ck_imports_failure_code": ("c", "imports", ["failure_code"]),
    "ck_import_attempts_status": ("c", "import_attempts", ["status"]),
    "ck_import_attempts_error_code": ("c", "import_attempts", ["error_code"]),
    "ck_alerts_status": ("c", "alerts", ["status"]),
    "ck_agent_actions_action": ("c", "agent_actions", ["action"]),
    "fk_products_vendor_id_vendors": ("f", "products", ["vendor_id"]),
    "fk_imports_vendor_id_vendors": ("f", "imports", ["vendor_id"]),
    "fk_import_attempts_import_id_imports": ("f", "import_attempts", ["import_id"]),
    "fk_alerts_import_id_imports": ("f", "alerts", ["import_id"]),
    "fk_agent_actions_alert_id_alerts": ("f", "agent_actions", ["alert_id"]),
    "pk_vendors": ("p", "vendors", ["id"]),
    "pk_products": ("p", "products", ["id"]),
    "pk_imports": ("p", "imports", ["id"]),
    "pk_import_attempts": ("p", "import_attempts", ["id"]),
    "pk_alerts": ("p", "alerts", ["id"]),
    "pk_agent_actions": ("p", "agent_actions", ["id"]),
}


@pytest.fixture
def conn(migrated_engine):
    with migrated_engine.connect() as connection:
        yield connection


def test_public_schema_holds_the_six_tables_and_alembic_version(conn):
    tables = conn.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    ).scalars()
    assert set(tables) == set(EXPECTED_COLUMNS) | {"alembic_version"}


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_columns_types_and_nullability_follow_the_spec(conn, table):
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = :table"
        ),
        {"table": table},
    )
    actual = {name: (data_type, nullable == "YES") for name, data_type, nullable in rows}
    assert actual == EXPECTED_COLUMNS[table]


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_every_id_is_bigserial(conn, table):
    default = conn.execute(
        text(
            "SELECT column_default FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = :table AND column_name = 'id'"
        ),
        {"table": table},
    ).scalar_one()
    assert default == f"nextval('{table}_id_seq'::regclass)"
    sequence_type = conn.execute(
        text("SELECT data_type FROM information_schema.sequences WHERE sequence_name = :name"),
        {"name": f"{table}_id_seq"},
    ).scalar_one()
    assert sequence_type == BIGINT


def test_there_are_no_native_enum_types(conn):
    assert conn.execute(text("SELECT count(*) FROM pg_type WHERE typtype = 'e'")).scalar_one() == 0


def test_every_constraint_has_its_deterministic_name(conn):
    rows = conn.execute(
        text(
            "SELECT c.conname, c.contype, t.relname,"
            "       array_agg(a.attname ORDER BY k.ord) AS columns"
            "  FROM pg_constraint c"
            "  JOIN pg_class t ON t.oid = c.conrelid"
            "  JOIN pg_namespace n ON n.oid = t.relnamespace"
            "  CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)"
            "  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum"
            " WHERE n.nspname = 'public' AND t.relname <> 'alembic_version'"
            " GROUP BY c.conname, c.contype, t.relname"
        )
    )
    actual = {name: (contype, table, list(columns)) for name, contype, table, columns in rows}
    assert actual == EXPECTED_CONSTRAINTS


def test_schema_is_at_the_single_head_revision(conn):
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1
    assert conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == heads
