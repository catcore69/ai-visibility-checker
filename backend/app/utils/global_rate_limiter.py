"""
Глобальный rate limiter на уровне Redis для синхронизации между Celery-воркерами.
Предотвращает превышение RPM-лимитов LLM API при параллельных задачах.
"""

import time
from typing import Optional

from app.cache.redis_cache import RedisCache
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GlobalRateLimiter:
    def __init__(self, cache: RedisCache):
        self.cache = cache

    async def acquire(self, model: str, max_per_minute: int, timeout: float = 60.0) -> bool:
        """
        Блокирует если за последнюю минуту уже было max_per_minute вызовов.
        Реализация через Redis sorted set с timestamps.
        Возвращает True если запрос разрешён.
        """
        key = f"rpm:{model}"
        now = time.time()
        window_start = now - 60

        client = await self.cache._get_client()

        pipe = client.pipeline()
        # Удаляем устаревшие записи
        pipe.zremrangebyscore(key, 0, window_start)
        # Считаем текущее количество
        pipe.zcard(key)
        # Добавляем текущий запрос
        pipe.zadd(key, {str(now): now})
        # TTL 70 секунд (с запасом)
        pipe.expire(key, 70)
        results = await pipe.execute()

        current_count = results[1]  # zcard до добавления
        if current_count >= max_per_minute:
            # Убираем только что добавленный элемент
            await client.zremrangebyscore(key, now, now + 0.001)
            logger.warning("global_rate_limit_hit", model=model, count=current_count, max=max_per_minute)
            return False

        return True

    async def wait_and_acquire(
        self, model: str, max_per_minute: int, max_wait: float = 30.0
    ) -> bool:
        """Ожидает и повторяет попытку до max_wait секунд."""
        import asyncio
        start = time.time()
        while time.time() - start < max_wait:
            if await self.acquire(model, max_per_minute):
                return True
            await asyncio.sleep(1)
        return False
