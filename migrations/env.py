# Flask-Migrate migration environment.
# Run migrations with: flask db upgrade (or flask db downgrade / flask db migrate).

import logging
from logging.config import fileConfig

from flask import current_app
import sqlalchemy as sa
from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")


def get_engine():
    try:
        return current_app.extensions["migrate"].db.get_engine()
    except (TypeError, AttributeError):
        return current_app.extensions["migrate"].db.engine


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace("%", "%%")
    except AttributeError:
        return str(get_engine().url).replace("%", "%%")


config.set_main_option("sqlalchemy.url", get_engine_url())
target_db = current_app.extensions["migrate"].db


def get_metadata():
    if hasattr(target_db, "metadatas"):
        return target_db.metadatas[None]
    return target_db.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode (SQL only, no DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=get_metadata(),
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode (with DB connection)."""
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info("No changes in schema detected.")

    conf_args = current_app.extensions["migrate"].configure_args
    if conf_args.get("process_revision_directives") is None:
        conf_args["process_revision_directives"] = process_revision_directives

    connectable = get_engine()
    with connectable.connect() as connection:
        _widen_the_version_column(connection)
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            # Alembic's default is varchar(32) and this project names revisions
            # after what they do, so fourteen of them are longer than that —
            # the first at 045. Without this a brand new database dies partway
            # through its very first upgrade, which is the one case nobody
            # exercises until they need it.
            version_table_column_type=sa.String(255),
            **conf_args,
        )
        with context.begin_transaction():
            context.run_migrations()


def _widen_the_version_column(connection):
    """Make sure alembic_version can hold this project's revision ids.

    Created here rather than left to Alembic, which would make it varchar(32).
    Fourteen revisions are named longer than that — the first at 045 — so a
    brand new database otherwise dies partway through its first upgrade, and
    then rolls the whole thing back so there is no evidence left to read.

    Widened as well as created, for a database stamped before this existed.
    """
    connection.execute(
        sa.text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            " version_num VARCHAR(255) NOT NULL,"
            " CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    connection.execute(
        sa.text(
            "ALTER TABLE alembic_version "
            "ALTER COLUMN version_num TYPE VARCHAR(255)"
        )
    )
    connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
