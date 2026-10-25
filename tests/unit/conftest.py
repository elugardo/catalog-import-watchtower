"""Unit-test fixtures: the parsed `openapi.yaml` contract (no database, no network)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi.yaml"


@pytest.fixture(scope="session")
def openapi() -> dict[str, Any]:
    with OPENAPI_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="session")
def components(openapi) -> dict[str, Any]:
    return openapi["components"]["schemas"]
