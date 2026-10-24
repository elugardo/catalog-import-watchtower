"""SQLAlchemy engine, session factory and declarative base."""

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import get_settings


class Base(DeclarativeBase):
    """Declarative base for every model (tables arrive with CIW-02)."""


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
    )


def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def check_database() -> bool:
    """Return True when `SELECT 1` succeeds; never raises, never hangs past the connect timeout."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any failure means "error" on the health endpoint
        return False
