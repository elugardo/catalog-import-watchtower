"""The Pydantic response models in `app/schemas/` match `openapi.yaml`.

For every schema of the contract, the model's serialised property names, its
required set and its nullable fields equal the YAML's, and every enum agrees
with the persisted values in `app.models.enums`. Response models are imported
only from `app.schemas`, which every router uses. The route-level drift test
against the generated schema of the app is `test_openapi_drift.py`.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any, get_args

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.models import enums
from app.schemas import (
    AgentActionOut,
    AlertListItemOut,
    AlertOut,
    AttemptOut,
    ErrorOut,
    HealthOut,
    ImportDetailOut,
    ImportOut,
    Page,
    ProductOut,
    UtcDateTime,
    ValidationErrorOut,
    VendorOut,
    resources,
)

MODELS: dict[str, type[BaseModel]] = {
    "Error": ErrorOut,
    "ValidationError": ValidationErrorOut,
    "Vendor": VendorOut,
    "Product": ProductOut,
    "Import": ImportOut,
    "ImportDetail": ImportDetailOut,
    "Attempt": AttemptOut,
    "Alert": AlertOut,
    "AlertListItem": AlertListItemOut,
    "AgentAction": AgentActionOut,
    "ImportList": Page[ImportOut],
    "VendorList": Page[VendorOut],
    "ProductList": Page[ProductOut],
    "AlertList": Page[AlertListItemOut],
    "Health": HealthOut,
}

# YAML enum schema -> (persisted tuple, the Literal in app.schemas.resources)
ENUMS = {
    "ImportStatus": (enums.IMPORT_STATUSES, resources.ImportStatus),
    "FailureCode": (enums.FAILURE_CODES, resources.FailureCode),
    "AttemptStatus": (enums.ATTEMPT_STATUSES, resources.AttemptStatus),
    "AlertStatus": (enums.ALERT_STATUSES, resources.AlertStatus),
    "AgentActionKind": (enums.AGENT_ACTIONS, resources.AgentActionKind),
}


def _resolve(ref: str, openapi: dict[str, Any]) -> dict[str, Any]:
    node: Any = openapi
    for part in ref.removeprefix("#/").split("/"):
        node = node[part]
    return node


def _flatten(schema: dict[str, Any], openapi: dict[str, Any]) -> tuple[dict, set[str]]:
    """Properties and required names of a YAML object schema, following `$ref` and `allOf`."""
    if "$ref" in schema:
        return _flatten(_resolve(schema["$ref"], openapi), openapi)
    properties = dict(schema.get("properties", {}))
    required = set(schema.get("required", []))
    for part in schema.get("allOf", []):
        part_properties, part_required = _flatten(part, openapi)
        properties.update(part_properties)
        required |= part_required
    return properties, required


def _yaml_nullable(prop: dict[str, Any]) -> bool:
    types = prop.get("type")
    if isinstance(types, list) and "null" in types:
        return True
    return any(option.get("type") == "null" for option in prop.get("anyOf", []))


def _model_nullable(prop: dict[str, Any]) -> bool:
    return any(option.get("type") == "null" for option in prop.get("anyOf", []))


def _model_schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema(mode="serialization")


@pytest.mark.parametrize("name", sorted(MODELS))
def test_model_property_names_equal_the_yaml_schema(name, openapi, components):
    yaml_properties, _ = _flatten(components[name], openapi)
    model_properties = _model_schema(MODELS[name])["properties"]

    assert set(model_properties) == set(yaml_properties)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_model_required_set_equals_the_yaml_schema(name, openapi, components):
    _, yaml_required = _flatten(components[name], openapi)
    model_required = set(_model_schema(MODELS[name]).get("required", []))

    assert model_required == yaml_required


@pytest.mark.parametrize("name", sorted(MODELS))
def test_model_nullable_fields_equal_the_yaml_schema(name, openapi, components):
    yaml_properties, _ = _flatten(components[name], openapi)
    model_properties = _model_schema(MODELS[name])["properties"]

    yaml_nullable = {key for key, prop in yaml_properties.items() if _yaml_nullable(prop)}
    model_nullable = {key for key, prop in model_properties.items() if _model_nullable(prop)}
    assert model_nullable == yaml_nullable


def test_every_yaml_object_schema_has_a_model(components):
    objects = {name for name, schema in components.items() if "enum" not in schema}
    assert objects == set(MODELS)


@pytest.mark.parametrize("name", sorted(ENUMS))
def test_enums_agree_between_yaml_models_and_schemas(name, components):
    persisted, literal = ENUMS[name]

    assert tuple(components[name]["enum"]) == persisted
    assert get_args(literal) == persisted


def test_health_enums_match_the_contract(openapi, components):
    yaml_properties, _ = _flatten(components["Health"], openapi)
    for key in ("status", "db"):
        assert _model_schema(HealthOut)["properties"][key]["enum"] == yaml_properties[key]["enum"]


def test_the_health_route_serves_the_app_schemas_model():
    from app.routers.health import get_health, router

    (route,) = [r for r in router.routes if getattr(r, "endpoint", None) is get_health]
    assert route.response_model is HealthOut


def test_validation_error_line_starts_at_one():
    with pytest.raises(ValidationError):
        ValidationErrorOut(line=0, column="sku", message="x")


def test_price_cents_rejects_a_fractional_number():
    product = {
        "id": 1,
        "vendor_id": 1,
        "sku": "CHAIR-001",
        "name": "Oak Dining Chair",
        "price_cents": 14999,
        "quantity": 8,
        "updated_at": datetime(2026, 10, 24, tzinfo=UTC),
    }
    assert ProductOut(**product).model_dump()["price_cents"] == 14999

    with pytest.raises(ValidationError):
        ProductOut(**{**product, "price_cents": 149.99})


def test_validation_errors_are_capped_at_twenty():
    base = {
        "id": 1,
        "vendor": {"id": 1, "display_name": "Sample Furnishings"},
        "filename": "invalid.csv",
        "sha256": "0" * 64,
        "row_count": 30,
        "product_count": None,
        "status": "FAILED",
        "failure_code": "VALIDATION_ERROR",
        "validation_error_count": 30,
        "inject_transient_failure": False,
        "attempt_count": 1,
        "recovered": False,
        "created_at": datetime(2026, 10, 24, tzinfo=UTC),
        "completed_at": None,
    }
    error = {"line": 2, "column": "price", "message": "bad"}
    assert len(ImportOut(**base, validation_errors=[error] * 20).validation_errors) == 20

    with pytest.raises(ValidationError):
        ImportOut(**base, validation_errors=[error] * 21)


def test_timestamps_serialise_as_utc_with_z_suffix():
    adapter = TypeAdapter(UtcDateTime)
    plus_two = datetime(2026, 10, 24, 14, 30, tzinfo=timezone(timedelta(hours=2)))

    assert adapter.dump_json(adapter.validate_python(plus_two)) == b'"2026-10-24T12:30:00Z"'


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValidationError):
        TypeAdapter(UtcDateTime).validate_python(datetime(2026, 10, 24, 12, 0))
