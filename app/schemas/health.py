"""`GET /api/health` response (`openapi.yaml` -> `Health`).

`app/routers/health.py` still declares its own identical model from CIW-01;
`tests/unit/test_contract_schemas.py` holds both to the YAML until CIW-03.2
(#4) wires the routers to `app.schemas`.
"""

from typing import Literal

from app.schemas.common import ApiModel


class HealthOut(ApiModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    agent_enabled: bool
    version: str
