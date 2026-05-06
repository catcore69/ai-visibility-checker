from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import engine, Base

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Создаёт таблицы если их нет (для разработки — в проде через Alembic)."""
    from app.db.models import report, lead_event, cached_response  # noqa — импорт для регистрации моделей
    async with engine.begin() as conn:
        pass  # Таблицы создаются через Alembic миграции
