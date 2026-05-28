import asyncio
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.celery_app import celery_app
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _make_session_factory(engine):
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


@celery_app.task(
    name="app.tasks.generate_report.generate_report_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def generate_report_task(self, report_id: str) -> None:
    """Запускает главный pipeline генерации отчёта."""
    async def _run():
        from app.core.pipeline import generate_report
        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        try:
            AsyncSessionLocal = _make_session_factory(engine)
            async with AsyncSessionLocal() as db:
                await generate_report(UUID(report_id), db)
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
    except Exception as exc:
        logger.error("generate_report_task_failed", report_id=report_id, error=str(exc))
        raise self.retry(exc=exc) from exc


@celery_app.task(name="app.tasks.generate_report.auto_send_report_after_timeout")
def auto_send_report_after_timeout(report_id: str) -> None:
    """Авто-отправка отчёта если эксперт не отреагировал за EXPERT_REVIEW_TIMEOUT_MINUTES."""
    async def _run():
        from app.db.repositories.report_repo import get_report, update_report_status
        from app.email.sender import EmailSender
        from app.integrations.telegram import TelegramNotifier
        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        try:
            AsyncSessionLocal = _make_session_factory(engine)
            async with AsyncSessionLocal() as db:
                report = await get_report(db, UUID(report_id))
                if not report:
                    return

                # Отправляем только если всё ещё в статусе ожидания
                if report.status != "awaiting_personal_note":
                    return

                await update_report_status(db, UUID(report_id), "sending_email", progress=99)
                # Этап 4.2 ТЗ: письмо + follow-up цепочка.
                from app.core.report_delivery import finalize_report_delivery
                await finalize_report_delivery(db, report)
                await update_report_status(db, UUID(report_id), "completed", progress=100)

                telegram = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)
                await telegram.notify_report_completed(report)

                logger.info("auto_sent_report", report_id=report_id)
        finally:
            await engine.dispose()

    asyncio.run(_run())


@celery_app.task(name="app.tasks.generate_report.cleanup_unverified_reports")
def cleanup_unverified_reports() -> None:
    """Удаляет неверифицированные заявки старше 24 часов."""
    async def _run():
        from app.db.repositories.report_repo import delete_old_unverified_reports
        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        try:
            AsyncSessionLocal = _make_session_factory(engine)
            async with AsyncSessionLocal() as db:
                cutoff = datetime.utcnow() - timedelta(hours=25)
                deleted = await delete_old_unverified_reports(db, older_than=cutoff)
                logger.info("cleanup_unverified", deleted=deleted)
        finally:
            await engine.dispose()

    asyncio.run(_run())


@celery_app.task(name="app.tasks.generate_report.cleanup_expired_cache")
def cleanup_expired_cache() -> None:
    """Удаляет истёкшие записи из таблицы кэша БД."""
    async def _run():
        from app.db.repositories.cache_repo import delete_expired_cache
        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        try:
            AsyncSessionLocal = _make_session_factory(engine)
            async with AsyncSessionLocal() as db:
                deleted = await delete_expired_cache(db)
                logger.info("cleanup_cache", deleted=deleted)
        finally:
            await engine.dispose()

    asyncio.run(_run())
