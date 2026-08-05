from logging.config import fileConfig

from alembic import context

import models
from config import SQLALCHEMY_DATABASE_URI
from utils.database import Base, engine
from utils.logger import logger

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URI)
target_metadata = Base.metadata


def process_revision_directives(migration_context, revision, directives) -> None:
    if not directives:
        return

    migration_script = directives[0]
    if migration_script.upgrade_ops.is_empty():
        directives[:] = []
        logger.info("No database schema changes detected")


def run_migrations_offline() -> None:
    context.configure(
        url=SQLALCHEMY_DATABASE_URI,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()