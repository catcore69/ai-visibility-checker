"""Follow-up цепочка email (Этап 4.2 ТЗ).

Новая логика (вместо старой проверки по Report.updated_at):
- При завершении отчёта (send_report_ready) бэкенд создаёт 3 записи
  в email_followups: day_3, day_10, day_30 с scheduled_at = now + Nd.
- Celery Beat каждые 15 минут вызывает scan_pending_followups.
- Таска сканирует email_followups, статус "pending", scheduled_at <= now,
  отправляет письмо через sender.send_followup_v2, помечает status="sent".

Отмена цепочки:
- При unsubscribe — все pending записи отчёта помечаются "cancelled" с
  cancelled_reason="user_unsubscribed".
- При cta_click (запись на разговор, скачивание чек-листа) — аналогично.
- См. report_repo.cancel_followups_for_report.
"""

import asyncio
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.celery_app import celery_app
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _make_session_factory(engine):
    return async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False,
        autocommit=False, autoflush=False,
    )


@celery_app.task(name="app.tasks.send_emails.scan_pending_followups")
def scan_pending_followups() -> None:
    """Сканирует email_followups, отправляет всё, что pending и просрочено.

    Beat вызывает каждые 15 минут. Идемпотентно — каждый followup
    помечается sent_at и status="sent" сразу после отправки.
    """
    async def _run():
        from app.db.models.email_followup import EmailFollowup
        from app.db.models.report import Report
        from app.email.sender import EmailSender

        engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
        try:
            SessionLocal = _make_session_factory(engine)
            async with SessionLocal() as db:
                now = datetime.utcnow()
                result = await db.execute(
                    select(EmailFollowup, Report)
                    .join(Report, Report.id == EmailFollowup.report_id)
                    .where(
                        and_(
                            EmailFollowup.status == "pending",
                            EmailFollowup.scheduled_at <= now,
                            # Подписан на цепочку — нет unsubscribed_at
                            Report.unsubscribed_at.is_(None),
                            # Отчёт завершён (а не в pending/failed)
                            Report.status == "completed",
                        )
                    )
                    .limit(50)  # бережём CPU email-сервера и SMTP-лимиты
                )
                rows = result.all()

                if not rows:
                    return

                sender = EmailSender(settings)
                for followup, report in rows:
                    try:
                        sent = await sender.send_followup_v2(report, followup.type)
                    except Exception as exc:
                        logger.error(
                            "followup_send_exception",
                            followup_id=str(followup.id),
                            type=followup.type,
                            error=str(exc),
                        )
                        followup.status = "failed"
                        followup.cancelled_reason = f"exception: {type(exc).__name__}"
                        await db.commit()
                        continue

                    if sent:
                        followup.status = "sent"
                        followup.sent_at = datetime.utcnow()
                        logger.info(
                            "followup_sent",
                            report_id=str(report.id),
                            type=followup.type,
                        )
                    else:
                        # SMTP отказал — оставляем pending, попробуем ещё раз
                        # на следующем тике Beat.
                        logger.warning(
                            "followup_smtp_failed_retrying",
                            followup_id=str(followup.id),
                        )
                    await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


# === LEGACY: оставляем для совместимости с beat_schedule ====================
# Старый таск send_followup_emails(day) больше не нужен — Beat дёргает
# scan_pending_followups. Но удалять полностью нельзя сразу: если на проде
# в очереди уже лежат отложенные задачи, они упадут. Оставляем заглушку.
@celery_app.task(name="app.tasks.send_emails.send_followup_emails")
def send_followup_emails(day: int) -> None:
    logger.info("legacy_send_followup_emails_called_noop", day=day)
