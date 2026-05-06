from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cached_response import CachedLLMResponse


async def get_cached_response(db: AsyncSession, cache_key: str) -> Optional[str]:
    result = await db.execute(
        select(CachedLLMResponse).where(
            CachedLLMResponse.cache_key == cache_key,
            CachedLLMResponse.expires_at > datetime.utcnow(),
        )
    )
    row = result.scalar_one_or_none()
    return row.response_text if row else None


async def set_cached_response(
    db: AsyncSession,
    cache_key: str,
    response_text: str,
    ttl_days: int = 7,
) -> None:
    expires_at = datetime.utcnow() + timedelta(days=ttl_days)
    cached = CachedLLMResponse(
        cache_key=cache_key,
        response_text=response_text,
        expires_at=expires_at,
    )
    db.add(cached)
    try:
        await db.commit()
    except Exception:
        await db.rollback()


async def delete_expired_cache(db: AsyncSession) -> int:
    result = await db.execute(
        delete(CachedLLMResponse).where(CachedLLMResponse.expires_at < datetime.utcnow())
    )
    await db.commit()
    return result.rowcount
