"""
Тесты LLM-поллеров.
Все внешние API мокируются — тесты не делают реальных сетевых запросов.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm_pollers.base import LLMResponse, BasePoller
from app.llm_pollers.openai_poller import OpenAIPoller
from app.llm_pollers.yandex_poller import YandexPoller
from app.llm_pollers.gigachat_poller import GigaChatPoller
from app.llm_pollers.gemini_poller import GeminiPoller
from app.llm_pollers.deepseek_poller import DeepSeekPoller
from app.llm_pollers.perplexity_poller import PerplexityPoller
from app.llm_pollers.alisa_poller import AlisaPoller


SAMPLE_RESPONSE = "Хороший выбор — ExampleBrand, также популярны CompetitorA и CompetitorB."


# ──────────────────────────────────────────────────────────────
# BasePoller
# ──────────────────────────────────────────────────────────────
class ConcretePoller(BasePoller):
    """Минимальная реализация для тестирования BasePoller."""
    model_name = "test_model"

    async def _query_raw(self, prompt: str) -> str:
        return SAMPLE_RESPONSE


@pytest.mark.asyncio
async def test_base_poller_cache_miss(mock_redis):
    """При промахе кэша вызывается _query_raw и результат сохраняется."""
    with patch("app.llm_pollers.base.RedisCache") as MockCache:
        cache_instance = MockCache.return_value
        cache_instance.get    = AsyncMock(return_value=None)
        cache_instance.set    = AsyncMock()
        cache_instance.exists = AsyncMock(return_value=False)

        poller = ConcretePoller()
        result = await poller.query("Тестовый запрос", "test_niche")

    assert result.response_text == SAMPLE_RESPONSE
    assert result.cached is False
    assert result.error is None
    cache_instance.set.assert_called_once()


@pytest.mark.asyncio
async def test_base_poller_cache_hit():
    """При попадании в кэш _query_raw не вызывается."""
    with patch("app.llm_pollers.base.RedisCache") as MockCache:
        cache_instance = MockCache.return_value
        cache_instance.get    = AsyncMock(return_value=SAMPLE_RESPONSE)
        cache_instance.exists = AsyncMock(return_value=True)

        poller = ConcretePoller()
        result = await poller.query("Тестовый запрос", "test_niche")

    assert result.response_text == SAMPLE_RESPONSE
    assert result.cached is True


@pytest.mark.asyncio
async def test_base_poller_retry_on_failure():
    """При ошибке поллер делает 3 попытки, затем возвращает error."""
    call_count = 0

    class FailingPoller(BasePoller):
        model_name = "failing_model"

        async def _query_raw(self, prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("API недоступен")

    with patch("app.llm_pollers.base.RedisCache") as MockCache:
        cache_instance = MockCache.return_value
        cache_instance.get    = AsyncMock(return_value=None)
        cache_instance.exists = AsyncMock(return_value=False)
        cache_instance.set    = AsyncMock()

        with patch("app.llm_pollers.base.asyncio.sleep", new_callable=AsyncMock):
            poller  = FailingPoller()
            result  = await poller.query("Тестовый запрос", "test_niche")

    assert result.error is not None
    assert call_count == 3  # 3 попытки


# ──────────────────────────────────────────────────────────────
# OpenAI Poller
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_openai_poller():
    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = SAMPLE_RESPONSE

    with patch("app.llm_pollers.openai_poller.AsyncOpenAI") as MockOpenAI, \
         patch("app.llm_pollers.base.RedisCache") as MockCache:

        cache_instance = MockCache.return_value
        cache_instance.get = AsyncMock(return_value=None)
        cache_instance.set = AsyncMock()

        client_instance = MockOpenAI.return_value
        client_instance.chat.completions.create = AsyncMock(return_value=mock_completion)

        poller = OpenAIPoller()
        result = await poller._query_raw("Тестовый запрос")

    assert result == SAMPLE_RESPONSE


# ──────────────────────────────────────────────────────────────
# Yandex Poller
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_yandex_poller():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "alternatives": [
                {"message": {"text": SAMPLE_RESPONSE}, "status": "ALTERNATIVE_STATUS_FINAL"}
            ]
        }
    }

    with patch("app.llm_pollers.yandex_poller.httpx.AsyncClient") as MockClient, \
         patch("app.llm_pollers.base.RedisCache") as MockCache:

        cache_instance = MockCache.return_value
        cache_instance.get = AsyncMock(return_value=None)
        cache_instance.set = AsyncMock()

        client_instance = MockClient.return_value.__aenter__.return_value
        client_instance.post = AsyncMock(return_value=mock_response)

        poller = YandexPoller()
        result = await poller._query_raw("Тестовый запрос")

    assert SAMPLE_RESPONSE in result


# ──────────────────────────────────────────────────────────────
# Alisa (XMLRiver) Poller
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_alisa_poller_neuro_block():
    """Проверяем парсинг блока <neuro> из XMLRiver ответа."""
    xml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<yandexsearch>
    <response>
        <neuro>{SAMPLE_RESPONSE}</neuro>
        <results>
            <grouping>
                <group><doc><url>https://example.com</url></doc></group>
            </grouping>
        </results>
    </response>
</yandexsearch>"""

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = xml_response

    with patch("app.llm_pollers.alisa_poller.httpx.AsyncClient") as MockClient, \
         patch("app.llm_pollers.base.RedisCache") as MockCache:

        cache_instance = MockCache.return_value
        cache_instance.get = AsyncMock(return_value=None)
        cache_instance.set = AsyncMock()

        client_instance = MockClient.return_value.__aenter__.return_value
        client_instance.get = AsyncMock(return_value=mock_response)

        poller = AlisaPoller()
        result = await poller._query_raw("Тестовый запрос")

    assert SAMPLE_RESPONSE in result


# ──────────────────────────────────────────────────────────────
# LLMResponse dataclass
# ──────────────────────────────────────────────────────────────
def test_llm_response_defaults():
    r = LLMResponse(
        model_name="chatgpt",
        prompt="тест",
        response_text="ответ"
    )
    assert r.error is None
    assert r.cached is False
    assert r.latency_ms == 0


def test_llm_response_with_error():
    r = LLMResponse(
        model_name="chatgpt",
        prompt="тест",
        response_text="",
        error="timeout"
    )
    assert r.error == "timeout"
    assert r.response_text == ""
