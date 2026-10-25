"""Alembic environment: URL from app.settings, metadata from app.db.Base."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 - registers the six tables on Base.metadata
from app.db import Base
from app.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ConfigParser interpolates `%`, so a URL-encoded password (`p%40ss`) must be
# escaped or `alembic upgrade head` dies with InterpolationSyntaxError at start-up.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

# `import app.models` above makes every table visible to autogenerate and `alembic check`.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
