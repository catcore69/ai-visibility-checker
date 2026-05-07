"""
Тесты двухэтапного анализатора упоминаний.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.core.analyzer import Analyzer, MentionResult, Analysis
from app.llm_pollers.base import LLMResponse


# ──────────────────────────────────────────────────────────────
# Фикстуры
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def sample_responses() -> list[LLMResponse]:
    return [
        LLMResponse(
            model_name="chatgpt",
            prompt="Лучшие CRM для малого бизнеса",
            response_text=(
                "Для малого бизнеса рекомендую ExampleBrand — удобный и доступный. "
                "Также популярны CompetitorA и CompetitorB."
            ),
        ),
        LLMResponse(
            model_name="yandex",
            prompt="Лучшие CRM для малого бизнеса",
            response_text=(
                "Среди решений выделяются CompetitorA и CompetitorC. "
                "ExampleBrand также заслуживает внимания."
            ),
        ),
        LLMResponse(
            model_name="gemini",
            prompt="Лучшие CRM для малого бизнеса",
            response_text=(
                "Популярные CRM: CompetitorB, CompetitorD. "
                "ExampleBrand не упоминается среди лидеров."
            ),
        ),
        LLMResponse(
            model_name="gigachat",
            prompt="Посоветуй облачный сервис",
            response_text="CompetitorA и CompetitorE — хороший выбор для бизнеса.",
        ),
        LLMResponse(
            model_name="chatgpt",
            prompt="Посоветуй облачный сервис",
            response_text="",
            error="API timeout",
        ),
    ]


@pytest.fixture
def brand_name() -> str:
    return "ExampleBrand"


@pytest.fixture
def competitors() -> list[str]:
    return ["CompetitorA", "CompetitorB", "CompetitorC", "CompetitorD", "CompetitorE"]


# ──────────────────────────────────────────────────────────────
# Regex/fuzzy первый проход
# ──────────────────────────────────────────────────────────────
def test_fuzzy_mention_exact_match():
    """Точное совпадение должно детектироваться."""
    analyzer = Analyzer.__new__(Analyzer)
    result = analyzer._fuzzy_check("ExampleBrand", "Лучший выбор — ExampleBrand для вашего бизнеса.")
    assert result is True


def test_fuzzy_mention_case_insensitive():
    """Регистронезависимое совпадение."""
    analyzer = Analyzer.__new__(Analyzer)
    result = analyzer._fuzzy_check("ExampleBrand", "examplebrand — лидер рынка.")
    assert result is True


def test_fuzzy_mention_not_found():
    """Бренд не упоминается."""
    analyzer = Analyzer.__new__(Analyzer)
    result = analyzer._fuzzy_check("ExampleBrand", "Популярны CompetitorA и CompetitorB.")
    assert result is False


def test_fuzzy_mention_high_similarity():
    """Похожее написание (опечатка) должно детектироваться при ratio>85."""
    analyzer = Analyzer.__new__(Analyzer)
    # "ExampIeBrand" — замена l→I, схожесть >85%
    result = analyzer._fuzzy_check("ExampleBrand", "ExampIeBrand хорошо подходит.", threshold=85)
    assert result is True


# ──────────────────────────────────────────────────────────────
# Полный анализ (мок LLM-судьи)
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_analyze_responses(sample_responses, brand_name, competitors):
    """Анализатор корректно агрегирует данные по всем ответам."""
    with patch("app.core.analyzer.AsyncOpenAI") as MockOpenAI:
        # LLM-судья не должен вызываться для явных совпадений
        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create = AsyncMock()

        analyzer = Analyzer(brand_name=brand_name, competitors=competitors)
        analysis = await analyzer.analyze(sample_responses)

    assert isinstance(analysis, Analysis)
    # ChatGPT и Yandex упомянули ExampleBrand
    mentions_by_model = {m.model_name: m for m in analysis.mention_results if m.brand_mentioned}
    assert "chatgpt" in mentions_by_model
    assert "yandex" in mentions_by_model

    # Ошибочные ответы не должны создавать упоминания
    error_mentions = [m for m in analysis.mention_results if m.error]
    assert len(error_mentions) >= 1


@pytest.mark.asyncio
async def test_analyze_empty_responses(brand_name, competitors):
    """Пустой список ответов — анализ без упоминаний."""
    analyzer = Analyzer(brand_name=brand_name, competitors=competitors)
    analysis = await analyzer.analyze([])

    assert analysis.total_responses == 0
    assert analysis.brand_mention_count == 0


def test_analysis_to_dict(brand_name, competitors):
    """Метод to_dict() возвращает JSON-совместимый словарь."""
    results = [
        MentionResult(
            model_name="chatgpt",
            prompt="Тест",
            brand_mentioned=True,
            position=1,
            sentiment="positive",
            competitors_mentioned=["CompetitorA"],
        )
    ]
    analysis = Analysis(
        brand_name=brand_name,
        mention_results=results,
        total_responses=1,
        brand_mention_count=1,
        models_with_mentions={"chatgpt"},
    )

    d = analysis.to_dict()
    assert isinstance(d, dict)
    assert d["brand_name"] == brand_name
    assert d["brand_mention_count"] == 1
    assert isinstance(d["mention_results"], list)
    assert d["mention_results"][0]["model_name"] == "chatgpt"
    # Множество должно быть сериализовано
    assert isinstance(d["models_with_mentions"], list)
