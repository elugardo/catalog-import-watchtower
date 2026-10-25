"""`openapi.yaml` says what spec section 7 and the CIW-02 criteria say.

The same validator also runs as its own CI step (`uv run openapi-spec-validator
openapi.yaml`); here it guards the local `uv run pytest tests/unit`.
"""

import re
from collections.abc import Iterator
from typing import Any

import pytest
from openapi_spec_validator import validate

OPERATIONS = {
    ("post", "/api/imports"),
    ("get", "/api/imports"),
    ("get", "/api/imports/{id}"),
    ("get", "/api/vendors"),
    ("get", "/api/products"),
    ("get", "/api/alerts"),
    ("get", "/api/health"),
}
LIST_ENDPOINTS = ["/api/imports", "/api/vendors", "/api/products", "/api/alerts"]
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
FORBIDDEN_PROPERTIES = {"csv_bytes", "normalized_name", "normalized_sku", "price", "price_dollars"}


def _walk(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}/{index}")


def _resolve(node: dict[str, Any], openapi: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        target: Any = openapi
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def _error_code_schema(response: dict[str, Any], openapi: dict[str, Any]) -> dict[str, Any]:
    return _resolve(response, openapi)["content"]["application/json"]["schema"]


def test_it_is_a_valid_openapi_3_1_document(openapi):
    assert openapi["openapi"].startswith("3.1")
    validate(openapi)  # raises on any violation


def test_exactly_the_seven_operations_of_spec_section_7(openapi):
    operations = {
        (method, path)
        for path, item in openapi["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }
    assert operations == OPERATIONS


def test_no_agent_retry_internal_acknowledge_or_dismiss_route(openapi):
    forbidden = re.compile(r"agent|retry|internal|ack|dismiss|oncall", re.IGNORECASE)
    assert not [path for path in openapi["paths"] if forbidden.search(path)]


def test_upload_is_multipart_with_the_three_fields(openapi):
    post = openapi["paths"]["/api/imports"]["post"]
    schema = post["requestBody"]["content"]["multipart/form-data"]["schema"]

    assert set(schema["properties"]) == {"vendor_name", "file", "inject_transient_failure"}
    assert set(schema["required"]) == {"vendor_name", "file"}
    assert schema["properties"]["vendor_name"]["type"] == "string"
    assert schema["properties"]["file"]["type"] == "string"
    assert schema["properties"]["file"]["format"] == "binary"
    flag = schema["properties"]["inject_transient_failure"]
    assert flag["enum"] == ["true", "false"]
    assert flag["default"] == "false"


def test_upload_documents_201_detail_and_its_4xx_codes(openapi):
    responses = openapi["paths"]["/api/imports"]["post"]["responses"]

    assert set(responses) == {"201", "400", "413"}
    created = responses["201"]["content"]["application/json"]["schema"]
    assert created == {"$ref": "#/components/schemas/ImportDetail"}
    examples = responses["400"]["content"]["application/json"]["examples"]
    assert {example["value"]["code"] for example in examples.values()} == {
        "MISSING_FIELD",
        "INVALID_FIELD",
        "INVALID_CONTENT_TYPE",
        "INVALID_ENCODING",
    }
    assert responses["413"]["content"]["application/json"]["example"]["code"] == "FILE_TOO_LARGE"


def test_import_detail_takes_an_integer_id_and_documents_404(openapi):
    get = openapi["paths"]["/api/imports/{id}"]["get"]

    (parameter,) = get["parameters"]
    assert parameter["name"] == "id" and parameter["in"] == "path"
    assert parameter["schema"]["type"] == "integer"
    assert set(get["responses"]) == {"200", "404"}
    assert get["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ImportDetail"
    }
    assert get["responses"]["404"]["content"]["application/json"]["example"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
def test_list_endpoints_take_limit_offset_and_document_invalid_query(path, openapi):
    get = openapi["paths"][path]["get"]
    parameters = {p["name"]: p for p in (_resolve(p, openapi) for p in get["parameters"])}

    assert parameters["limit"]["in"] == "query"
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "default": 50,
        "minimum": 1,
        "maximum": 100,
    }
    assert parameters["offset"]["schema"] == {"type": "integer", "default": 0, "minimum": 0}
    expected = {"limit", "offset", "vendor_id"} if path == "/api/products" else {"limit", "offset"}
    assert set(parameters) == expected

    assert set(get["responses"]) == {"200", "400"}
    invalid = _resolve(get["responses"]["400"], openapi)
    assert invalid["content"]["application/json"]["example"]["code"] == "INVALID_QUERY"

    envelope = _resolve(get["responses"]["200"]["content"]["application/json"]["schema"], openapi)
    assert set(envelope["properties"]) == {"items", "total"}
    assert set(envelope["required"]) == {"items", "total"}
    assert envelope["properties"]["total"]["type"] == "integer"


def test_products_vendor_id_is_an_optional_integer(openapi):
    (vendor_id,) = [
        p for p in openapi["paths"]["/api/products"]["get"]["parameters"] if "name" in p
    ]
    assert vendor_id["name"] == "vendor_id"
    assert vendor_id["required"] is False
    assert vendor_id["schema"]["type"] == "integer"


def test_every_4xx_uses_the_one_error_schema(openapi):
    error_ref = {"$ref": "#/components/schemas/Error"}
    seen = 0
    for item in openapi["paths"].values():
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            for status, response in operation["responses"].items():
                if status.startswith("4"):
                    assert _error_code_schema(response, openapi) == error_ref, (method, status)
                    seen += 1
    assert seen == 7  # POST 400 and 413, detail 404, the four list 400s
    error = openapi["components"]["schemas"]["Error"]
    assert set(error["required"]) == {"code", "message", "details"}
    assert error["properties"]["code"]["type"] == "string"
    assert error["properties"]["message"]["type"] == "string"
    assert error["properties"]["details"]["type"] == "array"
    assert error["properties"]["details"]["items"]["type"] == "object"


def test_no_response_exposes_storage_columns_or_a_dollar_price(openapi):
    names = {
        key
        for path, node in _walk(openapi["components"])
        if path.endswith("/properties") and isinstance(node, dict)
        for key in node
    }
    assert names.isdisjoint(FORBIDDEN_PROPERTIES)


def test_enum_values_are_upper_snake_case_and_there_is_no_recovered_status(openapi):
    schemas = openapi["components"]["schemas"]
    for name in ("ImportStatus", "FailureCode", "AttemptStatus", "AlertStatus", "AgentActionKind"):
        for value in schemas[name]["enum"]:
            assert re.fullmatch(r"[A-Z]+(_[A-Z]+)*", value), (name, value)
    all_values = [
        value for path, node in _walk(openapi) if path.endswith("/enum") for value in node
    ]
    assert "RECOVERED" not in all_values


def test_every_timestamp_is_a_utc_date_time_string(openapi):
    timestamps = [
        (path, node)
        for path, node in _walk(openapi["components"])
        if isinstance(node, dict) and node.get("format") == "date-time"
    ]
    assert len(timestamps) == 9  # product 1, import 2, attempt 2, alert 3, agent action 1
    for path, node in timestamps:
        types = node["type"] if isinstance(node["type"], list) else [node["type"]]
        assert "string" in types and set(types) <= {"string", "null"}, path
        assert "UTC" in node["description"] and "Z suffix" in node["description"], path
    # And no timestamp-looking property escapes the rule.
    stamped = {path.rsplit("/", 1)[-1] for path, _ in timestamps}
    assert stamped == {
        "created_at",
        "updated_at",
        "completed_at",
        "started_at",
        "finished_at",
        "claimed_at",
    }


def test_price_cents_and_quantity_are_integers(openapi):
    product = openapi["components"]["schemas"]["Product"]["properties"]
    assert product["price_cents"]["type"] == "integer"
    assert product["quantity"]["type"] == "integer"
    assert set(product) == {
        "id",
        "vendor_id",
        "sku",
        "name",
        "price_cents",
        "quantity",
        "updated_at",
    }


def test_import_and_its_detail_have_exactly_the_criteria_properties(openapi):
    schemas = openapi["components"]["schemas"]
    import_properties = schemas["Import"]["properties"]
    assert set(import_properties) == {
        "id",
        "vendor",
        "filename",
        "sha256",
        "row_count",
        "product_count",
        "status",
        "failure_code",
        "validation_errors",
        "validation_error_count",
        "inject_transient_failure",
        "attempt_count",
        "recovered",
        "created_at",
        "completed_at",
    }
    assert import_properties["validation_errors"]["maxItems"] == 20
    assert import_properties["vendor"] == {"$ref": "#/components/schemas/Vendor"}
    assert set(schemas["Vendor"]["properties"]) == {"id", "display_name"}

    detail_base, detail_extra = schemas["ImportDetail"]["allOf"]
    assert detail_base == {"$ref": "#/components/schemas/Import"}
    assert set(detail_extra["properties"]) == {"attempts", "alert", "agent_actions"}
    assert set(schemas["Attempt"]["properties"]) == {
        "number",
        "status",
        "error_code",
        "trace_id",
        "started_at",
        "finished_at",
    }
    assert set(schemas["Alert"]["properties"]) == {
        "id",
        "status",
        "reason",
        "claimed_at",
        "created_at",
        "updated_at",
    }
    assert set(schemas["AgentAction"]["properties"]) == {
        "id",
        "action",
        "tool_name",
        "reason_summary",
        "result",
        "created_at",
    }

    alert_base, alert_extra = schemas["AlertListItem"]["allOf"]
    assert alert_base == {"$ref": "#/components/schemas/Alert"}
    assert set(alert_extra["properties"]) == {
        "import_id",
        "import_status",
        "failure_code",
        "vendor_display_name",
        "filename",
    }


def test_health_matches_what_ciw_01_shipped(openapi):
    health = openapi["components"]["schemas"]["Health"]

    assert set(health["properties"]) == {"status", "db", "agent_enabled", "version"}
    assert set(health["required"]) == {"status", "db", "agent_enabled", "version"}
    assert health["properties"]["status"]["enum"] == ["ok", "degraded"]
    assert health["properties"]["db"]["enum"] == ["ok", "error"]
    assert health["properties"]["agent_enabled"]["type"] == "boolean"
    assert health["properties"]["version"]["type"] == "string"
    responses = openapi["paths"]["/api/health"]["get"]["responses"]
    assert set(responses) == {"200"}
