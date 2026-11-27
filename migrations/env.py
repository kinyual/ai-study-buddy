"""Alembic environment configuration for AI Study Buddy."""

from logging.config import fileConfig

from alembic import context

from backend.app.config import get_settings
from backend.app.database import engine
from backend.app.models import Base

config = context.config
settings = get_settings()

# Use the same database URL as the application instead of hardcoding one here.
config.set_main_option(
    "sqlalchemy.url", settings.database_url.replace("%", "%%")
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without opening a live database connection."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using the existing application engine."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
