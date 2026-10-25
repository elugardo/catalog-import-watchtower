"""The generated schema of the app (`/api/openapi.json`) says what `openapi.yaml` says.

No database: `create_app().openapi()` only walks the routes. For every
operation of either side, the test compares the path and method pairs, the
parameters (name, location, `required`, `minimum`, `maximum`, `default`),
the response status codes, the property names of every response body
(every status, `$ref`, `allOf` and nullable `anyOf` resolved, nested
objects and list items included) and the media type and property names of
the upload request body.

Component names differ between the two (`Page_VendorOut_` against
`VendorList`), so bodies are compared by structure after resolution, not by
name. The SPA catch-all and the docs routes are not in the generated schema
(`include_in_schema=False`, FastAPI's own docs routes), so nothing has to be
excluded by hand.
"""

from typing import Any

import pytest

from app.main import create_app

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
UNREACHABLE_DB = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nothing"


@pytest.fixture(scope="module")
def generated() -> dict[str, Any]:
    return create_app().openapi()


def _resolve(node: Any, document: dict[str, Any]) -> Any:
    while isinstance(node, dict) and "$ref" in node:
        target: Any = document
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def shape(node: Any, document: dict[str, Any]) -> Any:
    """The structure of a schema: `{property: shape}` for an object with properties,
    `["array", shape]` for an array, `"scalar"` for anything else.

    `$ref` is followed, `allOf` merged, and a nullable `anyOf` / `oneOf` reduced
    to its non-null option(s). An object without declared properties (a free-form
    `result` or `details[]` item) is a scalar on both sides.
    """
    node = _resolve(node, document)
    if not isinstance(node, dict):
        return "scalar"
    properties: dict[str, Any] = {}
    for part in node.get("allOf", []):
        part_shape = shape(part, document)
        if isinstance(part_shape, dict):
            properties.update(part_shape)
    for key in ("anyOf", "oneOf"):
        options = [
            shape(option, document)
            for option in node.get(key, [])
            if _resolve(option, document).get("type") != "null"
        ]
        if len(options) == 1 and not properties and "properties" not in node:
            return options[0]
        for option in options:
            if isinstance(option, dict):
                properties.update(option)
    for name, sub in node.get("properties", {}).items():
        properties[name] = shape(sub, document)
    if properties:
        return properties
    types = node.get("type")
    if types == "array" or (isinstance(types, list) and "array" in types):
        return ["array", shape(node.get("items", {}), document)]
    return "scalar"


def operations(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method, path): operation
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def _bounds(schema: dict[str, Any], document: dict[str, Any]) -> tuple[Any, Any, Any]:
    """`minimum`, `maximum` and `default` of a parameter schema, a nullable `anyOf` reduced."""
    schema = _resolve(schema, document)
    options = [o for o in schema.get("anyOf", []) if _resolve(o, document).get("type") != "null"]
    inner = _resolve(options[0], document) if len(options) == 1 else schema
    return (inner.get("minimum"), inner.get("maximum"), schema.get("default"))


def parameters(operation: dict[str, Any], document: dict[str, Any]) -> set[tuple[Any, ...]]:
    return {
        (
            p["name"],
            p["in"],
            bool(p.get("required", False)),
            *_bounds(p.get("schema", {}), document),
        )
        for p in (_resolve(p, document) for p in operation.get("parameters", []))
    }


def responses(operation: dict[str, Any], document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Status code -> media type -> body shape."""
    found: dict[str, dict[str, Any]] = {}
    for status, response in operation.get("responses", {}).items():
        content = _resolve(response, document).get("content", {})
        found[str(status)] = {
            media: shape(body.get("schema", {}), document) for media, body in content.items()
        }
    return found


def request_body(operation: dict[str, Any], document: dict[str, Any]) -> dict[str, Any] | None:
    body = _resolve(operation.get("requestBody"), document)
    if not body:
        return None
    return {
        media: sorted(_resolve(content["schema"], document).get("properties", {}))
        for media, content in body.get("content", {}).items()
    }


def test_the_same_operations(generated, openapi):
    assert set(operations(generated)) == set(operations(openapi))


def test_every_operation_has_the_same_parameters(generated, openapi):
    ours, theirs = operations(generated), operations(openapi)
    for key in sorted(set(ours) & set(theirs)):
        assert parameters(ours[key], generated) == parameters(theirs[key], openapi), key


def test_every_operation_has_the_same_status_codes(generated, openapi):
    ours, theirs = operations(generated), operations(openapi)
    for key in sorted(set(ours) & set(theirs)):
        assert set(ours[key]["responses"]) == set(theirs[key]["responses"]), key


def test_every_response_body_has_the_same_properties(generated, openapi):
    ours, theirs = operations(generated), operations(openapi)
    for key in sorted(set(ours) & set(theirs)):
        assert responses(ours[key], generated) == responses(theirs[key], openapi), key


def test_the_upload_request_body_matches(generated, openapi):
    ours, theirs = operations(generated), operations(openapi)
    for key in sorted(set(ours) & set(theirs)):
        assert request_body(ours[key], generated) == request_body(theirs[key], openapi), key
    assert request_body(ours[("post", "/api/imports")], generated) == {
        "multipart/form-data": ["file", "inject_transient_failure", "vendor_name"]
    }


def test_no_422_and_no_fastapi_validation_component(generated):
    for key, operation in operations(generated).items():
        assert "422" not in operation["responses"], key
    names = set(generated.get("components", {}).get("schemas", {}))
    assert "HTTPValidationError" not in names
    assert "ValidationError" not in names  # FastAPI's; ours is `ValidationErrorOut`


def test_the_schema_is_served_at_api_openapi_json(make_client, generated):
    response = make_client(DATABASE_URL=UNREACHABLE_DB).get("/api/openapi.json")

    assert response.status_code == 200
    served = response.json()
    assert set(operations(served)) == set(operations(generated))
    for key, operation in operations(served).items():
        assert "422" not in operation["responses"], key


# ---- the comparison itself can tell a difference ------------------------------


def test_shape_sees_a_nested_property_and_a_list_item():
    document = {
        "components": {
            "schemas": {
                "V": {"type": "object", "properties": {"id": {}, "name": {}}},
                "Page": {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"$ref": "#/components/schemas/V"}},
                        "total": {"type": "integer"},
                    },
                },
            }
        }
    }
    page = {"$ref": "#/components/schemas/Page"}
    assert shape(page, document) == {
        "items": ["array", {"id": "scalar", "name": "scalar"}],
        "total": "scalar",
    }
    document["components"]["schemas"]["V"]["properties"]["extra"] = {}
    assert shape(page, document)["items"][1] != {"id": "scalar", "name": "scalar"}


def test_shape_resolves_all_of_and_a_nullable_ref():
    document = {
        "components": {
            "schemas": {
                "A": {"type": "object", "properties": {"id": {}}},
                "B": {
                    "allOf": [
                        {"$ref": "#/components/schemas/A"},
                        {
                            "properties": {
                                "child": {
                                    "anyOf": [{"$ref": "#/components/schemas/A"}, {"type": "null"}]
                                }
                            }
                        },
                    ]
                },
            }
        }
    }
    assert shape({"$ref": "#/components/schemas/B"}, document) == {
        "id": "scalar",
        "child": {"id": "scalar"},
    }
