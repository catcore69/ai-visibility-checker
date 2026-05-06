from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_cache import RedisCache
from app.config import settings
from app.db.session import get_session


async def get_db() -> AsyncSession:
    async for session in get_session():
        yield session


_redis_cache: RedisCache | None = None


async def get_redis() -> RedisCache:
    global _redis_cache
    if _redis_cache is None:
        _redis_cache = RedisCache(settings.REDIS_URL)
    return _redis_cache


async def verify_internal_token(x_internal_token: str = Header(...)) -> None:
    """Защита внутренних эндпоинтов (для Telegram-бота эксперта)."""
    if x_internal_token != settings.INTERNAL_API_TOKEN:
        raise HTTPException(403, "Invalid internal token")
