from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from dzmm_vnext.config import Settings


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    settings = Settings.from_env()
    context.configure(url=settings.sync_database_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = Settings.from_env()
    settings.ensure_layout()
    from sqlalchemy import create_engine

    connectable = create_engine(settings.sync_database_url, future=True)
    with connectable.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
