from typing import Optional

import redis.asyncio as aioredis

from app.utils.logger import get_logger

logger = get_logger(__name__)


class RedisCache:
    def __init__(self, redis_url: str):
        self._redis: Optional[aioredis.Redis] = None
        self._url = redis_url

    async def _get_client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._url, encoding="utf-8", decode_responses=True)
        return self._redis

    async def get(self, key: str) -> Optional[str]:
        try:
            client = await self._get_client()
            return await client.get(key)
        except Exception as exc:
            logger.warning("redis_get_error", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: str, ttl: int = 86400) -> None:
        try:
            client = await self._get_client()
            await client.set(key, value, ex=ttl)
        except Exception as exc:
            logger.warning("redis_set_error", key=key, error=str(exc))

    async def exists(self, key: str) -> bool:
        try:
            client = await self._get_client()
            return bool(await client.exists(key))
        except Exception:
            return False

    async def incr(self, key: str) -> int:
        client = await self._get_client()
        return await client.incr(key)

    async def expire(self, key: str, ttl: int) -> None:
        client = await self._get_client()
        await client.expire(key, ttl)

    async def delete(self, key: str) -> None:
        try:
            client = await self._get_client()
            await client.delete(key)
        except Exception:
            pass

    async def llen(self, key: str) -> int:
        try:
            client = await self._get_client()
            return await client.llen(key)
        except Exception:
            return 0

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
