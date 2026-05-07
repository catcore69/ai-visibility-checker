"""
Интеграционные тесты пайплайна (с замоканными внешними зависимостями).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.pipeline import ReportPipeline
from app.db.models.report import Report


# ──────────────────────────────────────────────────────────────
# Фикстуры
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def sample_report() -> Report:
    report = MagicMock(spec=Report)
    report.id            = str(uuid.uuid4())
    report.brand_name    = "TestBrand"
    report.website_url   = "https://testbrand.ru"
    report.niche         = "B2B SaaS"
    report.email         = "owner@testbrand.ru"
    report.status        = "queued"
    report.niche_data    = None
    report.competitors   = None
    report.prompts       = None
    report.raw_responses = None
    report.analysis      = None
    report.recommendations = None
    return report


@pytest.fixture
def mock_niche_response() -> dict:
    return {
        "niche":       "B2B SaaS",
        "niche_key":   "b2b_saas",
        "description": "Корпоративные облачные решения",
        "keywords":    ["автоматизация", "CRM", "ERP", "облако"],
    }


@pytest.fixture
def mock_competitors_response() -> list[str]:
    return ["AmoCRM", "Bitrix24", "SalesForce", "Monday.com", "Notion"]


@pytest.fixture
def mock_prompts_response() -> list[str]:
    return [
        "Лучшие B2B SaaS-решения для предприятий",
        "Сравнение CRM-систем для корпоративного рынка",
        "Какие облачные инструменты используют крупные компании",
        "Топ ERP-систем для среднего бизнеса",
        "Автоматизация бизнес-процессов — лучшие решения",
    ]


# ──────────────────────────────────────────────────────────────
# Тесты отдельных шагов
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pipeline_detect_niche(sample_report, mock_niche_response):
    """Шаг 1: определение ниши через LLM."""
    with patch("app.core.pipeline.AsyncOpenAI") as MockOpenAI, \
         patch("app.core.pipeline.get_async_session") as mock_session:

        # Мокируем OpenAI JSON-ответ
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = (
            '{"niche": "B2B SaaS", "niche_key": "b2b_saas", '
            '"description": "Корпоративные облачные решения", '
            '"keywords": ["CRM", "ERP"]}'
        )
        client = MockOpenAI.return_value
        client.chat.completions.create = AsyncMock(return_value=mock_completion)

        mock_db = AsyncMock()
        mock_session.return_value.__aenter__.return_value = mock_db

        pipeline = ReportPipeline(report=sample_report, db=mock_db)
        niche_data = await pipeline._detect_niche()

    assert niche_data["niche"] == "B2B SaaS"
    assert "keywords" in niche_data


@pytest.mark.asyncio
async def test_pipeline_find_competitors(sample_report, mock_niche_response, mock_competitors_response):
    """Шаг 2: поиск конкурентов через LLM."""
    with patch("app.core.pipeline.AsyncOpenAI") as MockOpenAI:
        import json
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = json.dumps(
            {"competitors": mock_competitors_response}
        )
        client = MockOpenAI.return_value
        client.chat.completions.create = AsyncMock(return_value=mock_completion)

        mock_db = AsyncMock()
        pipeline = ReportPipeline(report=sample_report, db=mock_db)
        competitors = await pipeline._find_competitors(mock_niche_response)

    assert isinstance(competitors, list)
    assert len(competitors) <= 5
    assert all(isinstance(c, str) for c in competitors)


@pytest.mark.asyncio
async def test_pipeline_poll_models_parallel(
    sample_report,
    mock_niche_response,
    mock_prompts_response,
    mock_competitors_response,
):
    """Шаг 4: параллельный опрос моделей."""
    from app.llm_pollers.base import LLMResponse

    fake_response = LLMResponse(
        model_name="chatgpt",
        prompt=mock_prompts_response[0],
        response_text="TestBrand — хороший выбор для B2B.",
    )

    with patch("app.core.pipeline.get_enabled_pollers") as mock_pollers:
        mock_poller = AsyncMock()
        mock_poller.model_name = "chatgpt"
        mock_poller.query = AsyncMock(return_value=fake_response)
        mock_pollers.return_value = [mock_poller]

        mock_db = AsyncMock()
        pipeline = ReportPipeline(report=sample_report, db=mock_db)
        responses = await pipeline._poll_all_models(
            prompts=mock_prompts_response[:2],
            niche_key=mock_niche_response["niche_key"],
        )

    assert isinstance(responses, list)
    assert len(responses) > 0
    assert all(isinstance(r, LLMResponse) for r in responses)


# ──────────────────────────────────────────────────────────────
# Полный пайплайн (смоук-тест)
# ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_full_pipeline_smoke(
    sample_report,
    mock_niche_response,
    mock_competitors_response,
    mock_prompts_response,
):
    """
    Смоук-тест: пайплайн завершается без исключений при замоканных зависимостях.
    Проверяем что статус report изменяется на 'done'.
    """
    import json
    from app.llm_pollers.base import LLMResponse

    fake_llm_response = LLMResponse(
        model_name="chatgpt",
        prompt="Тест",
        response_text=(
            "TestBrand — популярное решение. "
            "AmoCRM также известен. Bitrix24 занимает лидирующие позиции."
        ),
    )

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit  = AsyncMock()
    mock_db.refresh = AsyncMock()

    with patch("app.core.pipeline.AsyncOpenAI") as MockOpenAI, \
         patch("app.core.pipeline.get_enabled_pollers") as mock_pollers, \
         patch("app.core.pipeline.ReportBuilder") as MockBuilder, \
         patch("app.core.pipeline.EmailSender") as MockEmail, \
         patch("app.core.pipeline.TelegramNotifier") as MockTelegram, \
         patch("app.core.pipeline.GoogleSheetsCRM") as MockSheets:

        # OpenAI: возвращает JSON для всех вызовов
        def make_completion(text: str):
            c = MagicMock()
            c.choices[0].message.content = text
            return c

        niche_json       = json.dumps(mock_niche_response)
        competitors_json = json.dumps({"competitors": mock_competitors_response})
        prompts_json     = json.dumps({"prompts": mock_prompts_response})
        recs_json        = json.dumps({"recommendations": [
            {"title": "Оптимизировать контент", "description": "Создать статьи",
             "effort": "medium", "impact": "+10 баллов"}
        ]})

        MockOpenAI.return_value.chat.completions.create = AsyncMock(side_effect=[
            make_completion(niche_json),
            make_completion(competitors_json),
            make_completion(prompts_json),
            make_completion(recs_json),
        ])

        # Поллер
        mock_poller = AsyncMock()
        mock_poller.model_name = "chatgpt"
        mock_poller.query = AsyncMock(return_value=fake_llm_response)
        mock_pollers.return_value = [mock_poller]

        # PDF builder
        mock_builder = MockBuilder.return_value
        mock_builder.build = AsyncMock(return_value="https://s3.example.com/report.pdf")

        # Email / Telegram / Sheets — без реальных вызовов
        MockEmail.return_value.send_report_ready   = AsyncMock()
        MockTelegram.return_value.notify_report_ready_for_review = AsyncMock()
        MockSheets.return_value.add_lead           = AsyncMock()

        pipeline = ReportPipeline(report=sample_report, db=mock_db)
        await pipeline.run()

    # После выполнения статус должен смениться
    assert sample_report.status in ("done", "awaiting_personal_note")
