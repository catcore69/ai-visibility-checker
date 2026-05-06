import sentry_sdk
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.api.health import router as health_router
from app.api.v1.routes import router as api_v1_router
from app.db.session import init_db
from app.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", env=settings.APP_ENV)
    await init_db()
    yield
    logger.info("shutdown")


# Sentry
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        traces_sample_rate=0.1,
    )

app = FastAPI(
    title="AI Visibility Checker API",
    description="Бэкенд инструмента проверки видимости бренда в ИИ-ассистентах",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS — разрешаем фронтенд
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.STUDIO_FULL_URL,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(api_v1_router, prefix="/api/v1")
