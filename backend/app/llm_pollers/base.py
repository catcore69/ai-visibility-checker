import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class RateLimitError(Exception):
    pass


@dataclass
class LLMResponse:
    model_name: str
    prompt: str
    response_text: str
    error: Optional[str] = None
    cached: bool = False
    latency_ms: int = 0


class BasePoller(ABC):
    name: str
    display_name: str
    model: str

    def __init__(self, cache, config):
        self.cache = cache
        self.config = config

    @abstractmethod
    async def _query_raw(self, prompt: str) -> str:
        """Реальный вызов API."""
        pass

    async def query(self, prompt: str, niche_key: str) -> LLMResponse:
        """С кэшем и retry (3 попытки, exponential backoff)."""
        cache_key = f"{self.name}:{niche_key}:{hash(prompt)}"

        cached_text = await self.cache.get(cache_key)
        if cached_text:
            return LLMResponse(
                model_name=self.name,
                prompt=prompt,
                response_text=cached_text,
                cached=True,
            )

        for attempt in range(3):
            try:
                start = time.monotonic()
                response_text = await self._query_raw(prompt)
                latency = int((time.monotonic() - start) * 1000)

                ttl = self.config.CACHE_TTL_DAYS * 24 * 3600
                await self.cache.set(cache_key, response_text, ttl=ttl)

                logger.debug(
                    "llm_response",
                    model=self.name,
                    latency_ms=latency,
                    cached=False,
                )
                return LLMResponse(
                    model_name=self.name,
                    prompt=prompt,
                    response_text=response_text,
                    latency_ms=latency,
                )
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning("rate_limit", model=self.name, attempt=attempt, wait=wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                logger.error("llm_error", model=self.name, attempt=attempt, error=str(exc))
                if attempt == 2:
                    return LLMResponse(
                        model_name=self.name,
                        prompt=prompt,
                        response_text="",
                        error=str(exc),
                    )
                await asyncio.sleep(2 ** attempt)

        return LLMResponse(
            model_name=self.name,
            prompt=prompt,
            response_text="",
            error="Failed after 3 retries",
        )
