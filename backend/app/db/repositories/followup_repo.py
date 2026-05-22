"""Репозиторий для email_followups (Этап 4.2 ТЗ)."""

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.email_followup import EmailFollowup
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Расписание цепочки. Если в будущем понадобится 5-7 шагов — добавляем сюда.
FOLLOWUP_SCHEDULE = [
    ("day_3", 3),
    ("day_10", 10),
    ("day_30", 30),
]


async def create_followup_chain(db: AsyncSession, report_id: UUID) -> int:
    """Создаёт три записи email_followups (day_3 / day_10 / day_30).

    Если для этого отчёта уже есть pending записи — пропускаем, чтобы не дублировать.
    """
    # Идемпотентность
    existing = await db.execute(
        select(EmailFollowup).where(EmailFollowup.report_id == report_id)
    )
    if existing.scalars().first():
        return 0

    now = datetime.utcnow()
    created = 0
    for ftype, days in FOLLOWUP_SCHEDULE:
        followup = EmailFollowup(
            report_id=report_id,
            type=ftype,
            scheduled_at=now + timedelta(days=days),
            status="pending",
        )
        db.add(followup)
        created += 1
    await db.commit()
    logger.info("followup_chain_created", report_id=str(report_id), count=created)
    return created


async def cancel_followups_for_report(
    db: AsyncSession,
    report_id: UUID,
    reason: str,
) -> int:
    """Помечает все pending записи отчёта как cancelled с указанной причиной.

    Триггеры (по ТЗ):
    - "user_unsubscribed" — клиент кликнул unsubscribe-ссылку
    - "call_scheduled" — записался на разговор (придёт из Bitrix24 webhook позже)
    - "checklist_downloaded" — скачал чек-лист
    - "report_failed" — отчёт упал
    """
    result = await db.execute(
        update(EmailFollowup)
        .where(
            and_(
                EmailFollowup.report_id == report_id,
                EmailFollowup.status == "pending",
            )
        )
        .values(status="cancelled", cancelled_reason=reason)
    )
    await db.commit()
    if result.rowcount:
        logger.info(
            "followup_chain_cancelled",
            report_id=str(report_id),
            reason=reason,
            count=result.rowcount,
        )
    return result.rowcount


async def get_followup_by_token(
    db: AsyncSession,
    report_id: UUID,
) -> Optional[list[EmailFollowup]]:
    result = await db.execute(
        select(EmailFollowup).where(EmailFollowup.report_id == report_id)
    )
    return list(result.scalars().all())
