import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass  # alembic.ini may use env-var syntax unsupported by configparser

# Импортируем все модели для автогенерации миграций
from app.db.base import Base
from app.db.models import report, lead_event, cached_response, niche_prompt_template  # noqa

target_metadata = Base.metadata


def get_url() -> str:
    """Читаем DATABASE_URL_SYNC из env; фоллбэк — значение из alembic.ini."""
    url = os.environ.get("DATABASE_URL_SYNC", "")
    if not url:
        url = config.get_main_option("sqlalchemy.url", "")
    return url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Подменяем URL до создания движка
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
