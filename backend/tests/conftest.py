"""
Общие фикстуры для тестов AI Visibility Checker.
"""
import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.main import app
from app.db.models.report import Report
from app.db.models.lead_event import LeadEvent
from app.db.models.cached_response import CachedLLMResponse
from app.db.base import Base

# ──────────────────────────────────────────────────────────────
# Event loop
# ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop() -> Generator:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ──────────────────────────────────────────────────────────────
# In-memory SQLite для тестов
# ──────────────────────────────────────────────────────────────
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    async_session = async_sessionmaker(test_engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback()


# ──────────────────────────────────────────────────────────────
# HTTP client
# ──────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c


# ──────────────────────────────────────────────────────────────
# Образцовые данные
# ──────────────────────────────────────────────────────────────
@pytest.fixture
def sample_report_data() -> dict:
    return {
        "website_url": "https://example.com",
        "brand_name":  "ExampleBrand",
        "niche":       "SaaS для малого бизнеса",
        "email":       "test@example.com",
    }


@pytest.fixture
def sample_niche_data() -> dict:
    return {
        "niche":       "SaaS для малого бизнеса",
        "niche_key":   "saas_smb",
        "description": "Программное обеспечение как услуга для малого и среднего бизнеса",
        "keywords":    ["CRM", "учёт", "автоматизация", "облако"],
    }


@pytest.fixture
def sample_competitors() -> list[str]:
    return ["CompetitorA", "CompetitorB", "CompetitorC", "CompetitorD", "CompetitorE"]


@pytest.fixture
def sample_prompts() -> list[str]:
    return [
        "Какие лучшие CRM-системы для малого бизнеса?",
        "Посоветуй облачный сервис для учёта клиентов",
        "Топ SaaS-решений для автоматизации продаж",
        "Какой сервис выбрать для ведения клиентской базы?",
        "Лучшие инструменты для малого бизнеса онлайн",
    ]


@pytest.fixture
def sample_llm_response_text() -> str:
    return (
        "Для малого бизнеса хорошо подходят: ExampleBrand — удобный интерфейс и "
        "доступная цена, CompetitorA — широкая интеграция, CompetitorB — мощная аналитика."
    )


@pytest.fixture
def mock_redis():
    """Мок Redis-клиента."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.exists = AsyncMock(return_value=False)
    mock.incr = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    mock.llen = AsyncMock(return_value=0)
    mock.zadd = AsyncMock(return_value=1)
    mock.zcount = AsyncMock(return_value=0)
    return mock


@pytest.fixture
def mock_s3():
    """Мок S3-клиента."""
    mock = MagicMock()
    mock.upload_bytes = AsyncMock(return_value="reports/test-id/report.pdf")
    mock.generate_presigned_url = AsyncMock(return_value="https://s3.example.com/reports/test-id/report.pdf?signature=abc")
    return mock


@pytest.fixture
def mock_telegram():
    """Мок Telegram-нотификатора."""
    mock = AsyncMock()
    mock.notify_pipeline_started    = AsyncMock()
    mock.notify_report_ready_for_review = AsyncMock()
    mock.notify_pending_verification = AsyncMock()
    mock.notify_cta_click           = AsyncMock()
    mock.notify_high_risk           = AsyncMock()
    return mock
