import asyncio
import hashlib
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
    async def _query_raw(self, prompt: str, region: str = "") -> str:
        """Реальный вызов API. region — регион клиента (для поллеров, которым
        нужна гео-привязка: yandex_ai_search, google_ai_overview). Остальные
        могут игнорировать."""
        pass

    async def query(self, prompt: str, niche_key: str, region: str = "") -> LLMResponse:
        """С кэшем и retry (3 попытки, exponential backoff)."""
        # Срочный фикс: hash() для строк рандомизирован между процессами
        # (PYTHONHASHSEED) → ключ менялся после рестарта воркера и кеш промахивался.
        # Используем детерминированный md5.
        prompt_hash = hashlib.md5(prompt.encode("utf-8")).hexdigest()[:16]
        cache_key = f"{self.name}:{niche_key}:{prompt_hash}"

        cached_text = await self.cache.get(cache_key)
        if cached_text:
            return LLMResponse(
                model_name=self.name,
                prompt=prompt,
                response_text=cached_text,
                cached=True,
            )

        # Жёсткий таймаут на ОДИН вызов модели. Без него зависший HTTP-запрос
        # (модель/прокси держит соединение и не отвечает) морозит весь asyncio.gather
        # опроса — отчёт навсегда застревает на polling_models. На холодном кеше это
        # вскрывается сразу. wait_for отменяет повисший вызов, дальше — обычный ретрай.
        call_timeout = getattr(self.config, "LLM_CALL_TIMEOUT", 45)

        for attempt in range(3):
            try:
                start = time.monotonic()
                response_text = await asyncio.wait_for(
                    self._query_raw(prompt, region=region), timeout=call_timeout
                )
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
