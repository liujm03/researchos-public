from logging.config import fileConfig

from sqlalchemy import Index, engine_from_config, pool

from alembic import context
from app import models  # noqa: F401
from app.core.config import get_settings
from app.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata

# These PostgreSQL-only expression indexes are maintained by revision a04920260930.
# SQLAlchemy metadata cannot declare them portably for the SQLite preview. Restrict
# the autogenerate exception to reflected, unmatched indexes on the exact tables.
_PG_SEARCH_INDEXES = frozenset(
    {
        ("papers", "ix_papers_search_simple_gin"),
        ("research_projects", "ix_research_projects_search_simple_gin"),
        ("tasks", "ix_tasks_search_simple_gin"),
        ("paper_notes", "ix_paper_notes_search_simple_gin"),
    }
)


def _include_object(
    object_: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    if (
        type_ != "index"
        or not reflected
        or compare_to is not None
        or not isinstance(object_, Index)
    ):
        return True
    table = object_.table
    if table is None or name is None:
        return True
    return (table.name, name) not in _PG_SEARCH_INDEXES


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object if connection.dialect.name == "postgresql" else None,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
