"""SQLAlchemy engine, session factory and declarative base."""

import logging
import threading
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import get_settings

log = logging.getLogger(__name__)

# Every constraint gets a deterministic name, so a later additive migration can
# drop and recreate a CHECK by name to add a value (spec section 6). A CHECK is
# declared with a short name (`status`) and becomes `ck_<table>_status`.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every model in `app/models/`."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


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


def _probe_database() -> bool:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means "error" on the health endpoint
        # Type only: the driver's message can carry the host and user from the DSN.
        log.warning("database health probe failed: %s", type(exc).__name__)
        return False


def health_deadline_seconds() -> float:
    """How long `/api/health` waits for the database before reporting `error`."""
    return get_settings().database_connect_timeout_seconds + 1.0


def check_database() -> bool:
    """Return True when `SELECT 1` succeeds within the health deadline; never raises.

    The connect timeout bounds the TCP handshake but not name resolution: when
    the `db` container is stopped, resolving its name can take several seconds
    on some resolvers. The probe therefore runs in a daemon thread and the
    caller gives up at the deadline; the thread ends on its own shortly after.
    """
    outcome: list[bool] = []
    probe = threading.Thread(
        target=lambda: outcome.append(_probe_database()), name="db-health-probe", daemon=True
    )
    probe.start()
    probe.join(timeout=health_deadline_seconds())
    return bool(outcome) and outcome[0]
