"""`GET /api/health` response (`openapi.yaml` -> `Health`), served by `app/routers/health.py`."""

from typing import Literal

from app.schemas.common import ApiModel


class HealthOut(ApiModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    agent_enabled: bool
    version: str
