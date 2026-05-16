import asyncio
from datetime import datetime, timedelta

from app.celery_app import celery_app
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.tasks.send_emails.send_followup_emails")
def send_followup_emails(day: int) -> None:
    """Отправляет follow-up письма через N дней после завершения отчёта."""
    async def _run():
        from app.db.session import AsyncSessionLocal
        from app.db.models.report import Report
        from app.db.models.lead_event import LeadEvent
        from app.db.repositories.report_repo import log_event
        from app.email.sender import EmailSender
        from app.config import settings
        from sqlalchemy import select, and_

        async with AsyncSessionLocal() as db:
            # Ищем отчёты, завершённые ровно N дней назад (±1 час)
            target_start = datetime.utcnow() - timedelta(days=day, hours=1)
            target_end = datetime.utcnow() - timedelta(days=day) + timedelta(hours=1)

            # Отчёты завершены в целевой период
            result = await db.execute(
                select(Report).where(
                    and_(
                        Report.status == "completed",
                        Report.updated_at >= target_start,
                        Report.updated_at <= target_end,
                    )
                )
            )
            reports = result.scalars().all()

            # Проверяем что follow-up ещё не отправлялся
            event_key = f"followup_day_{day}_sent"
            sender = EmailSender(settings)

            for report in reports:
                # Проверяем нет ли уже события
                already_sent = await db.execute(
                    select(LeadEvent).where(
                        and_(
                            LeadEvent.report_id == report.id,
                            LeadEvent.event_type == event_key,
                        )
                    )
                )
                if already_sent.scalar_one_or_none():
                    continue

                sent = await sender.send_followup(report, day)
                if sent:
                    await log_event(db, report.id, event_key)
                    logger.info("followup_sent", report_id=str(report.id), day=day)

    _run_async(_run())
