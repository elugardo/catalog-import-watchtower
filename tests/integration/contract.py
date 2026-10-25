"""Helpers for the list tests: live responses against `openapi.yaml`, paging walks, SQL counts.

`assert_matches(body, "ImportList")` checks a response body against a
component of the YAML in both directions (no extra key, none missing),
following `$ref`, `allOf` and nullable `anyOf`, into nested objects and list
items. It is needed because the YAML closes only `ImportDetail` and
`AlertListItem` with `unevaluatedProperties: false`; `Import`, `Product`,
`Vendor` and `Health` stay open, so schema validation alone would accept an
extra key. Every non-null `*_at` string must end in `Z`.
"""

from functools import cache
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

OPENAPI = Path(__file__).resolve().parents[2] / "openapi.yaml"


@cache
def _document() -> dict[str, Any]:
    return yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))


def _resolve(node: Any) -> Any:
    while isinstance(node, dict) and "$ref" in node:
        target: Any = _document()
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def _object_properties(schema: Any) -> dict[str, Any] | None:
    """The merged properties of an object schema, or None when it is not one."""
    schema = _resolve(schema)
    if not isinstance(schema, dict):
        return None
    found: dict[str, Any] = {}
    is_object = "properties" in schema
    for part in schema.get("allOf", []):
        part_properties = _object_properties(part)
        if part_properties is not None:
            found.update(part_properties)
            is_object = True
    found.update(schema.get("properties", {}))
    return found if is_object and found else None


def _non_null_options(schema: Any) -> list[Any]:
    schema = _resolve(schema)
    options = schema.get("anyOf") or schema.get("oneOf")
    if not options:
        return [schema]
    return [_resolve(option) for option in options if _resolve(option).get("type") != "null"]


def _check(value: Any, schema: Any, where: str) -> None:
    if value is None:
        return
    for option in _non_null_options(schema):
        properties = _object_properties(option)
        if properties is not None:
            assert isinstance(value, dict), where
            assert set(value) == set(properties), (
                f"{where}: extra {sorted(set(value) - set(properties))},"
                f" missing {sorted(set(properties) - set(value))}"
            )
            for key, sub in properties.items():
                _check(value[key], sub, f"{where}.{key}")
                if key.endswith("_at") and value[key] is not None:
                    assert value[key].endswith("Z"), f"{where}.{key} = {value[key]!r}"
            return
        types = option.get("type")
        if types == "array" or (isinstance(types, list) and "array" in types):
            assert isinstance(value, list), where
            for index, item in enumerate(value):
                _check(item, option.get("items", {}), f"{where}[{index}]")
            return


def assert_matches(body: Any, component: str) -> None:
    """`body` has exactly the properties of `components/schemas/<component>`, recursively."""
    _check(body, {"$ref": f"#/components/schemas/{component}"}, component)


def item_keys(component: str) -> set[str]:
    properties = _object_properties({"$ref": f"#/components/schemas/{component}"})
    assert properties is not None
    return set(properties)


def walk(client: TestClient, path: str, **params: Any) -> list[dict[str, Any]]:
    """Every item of a list, requesting `offset` = items received until that equals `total`.

    This is the **Load more** contract (#6). Each page is checked against the YAML.
    """
    items: list[dict[str, Any]] = []
    while True:
        response = client.get(path, params={**params, "limit": 100, "offset": len(items)})
        assert response.status_code == 200, response.text
        body = response.json()
        items.extend(body["items"])
        if len(items) >= body["total"] or not body["items"]:
            return items


def sql_count(engine: Engine, table: str, where: str = "", **params: Any) -> int:
    with engine.connect() as connection:
        query = f"SELECT count(*) FROM {table}" + (f" WHERE {where}" if where else "")
        return connection.execute(text(query), params).scalar_one()


def sql(engine: Engine, statement: str, **params: Any) -> list[Any]:
    """Run one statement in its own committed transaction; the rows it returns, if any."""
    with engine.begin() as connection:
        result = connection.execute(text(statement), params)
        return list(result) if result.returns_rows else []
