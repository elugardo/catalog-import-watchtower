"""`GET /api/health`: always 200 while the process is up."""

from fastapi import APIRouter

from app.db import check_database
from app.schemas import HealthOut
from app.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut, summary="Liveness and database reachability")
def get_health() -> HealthOut:
    settings = get_settings()
    db_ok = check_database()
    return HealthOut(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "error",
        agent_enabled=settings.agent_enabled,
        version=settings.app_version,
    )
