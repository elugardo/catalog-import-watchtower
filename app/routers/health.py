"""`GET /api/health`: always 200 while the process is up."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db import check_database
from app.settings import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "error"]
    agent_enabled: bool
    version: str


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    settings = get_settings()
    db_ok = check_database()
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "error",
        agent_enabled=settings.agent_enabled,
        version=settings.app_version,
    )
