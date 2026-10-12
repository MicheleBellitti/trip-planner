"""Alembic environment: async engine, URL from app.config.Settings, metadata from app.db.

Two ways in:
- the `alembic` command line, which connects with DATABASE_URL;
- in-process callers (tests) that pass an open sync connection in
  `config.attributes["connection"]`, which is used as-is.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import Base

config = context.config
target_metadata = Base.metadata
external_connection: Connection | None = config.attributes.get("connection")

if config.config_file_name is not None and external_connection is None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def database_url() -> str:
    return get_settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of connecting (`alembic upgrade head --sql`)."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    if external_connection is not None:
        do_run_migrations(external_connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
