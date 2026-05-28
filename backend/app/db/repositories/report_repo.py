from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.report import Report
from app.db.models.lead_event import LeadEvent


async def create_report(db: AsyncSession, report: Report) -> Report:
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


async def get_report(db: AsyncSession, report_id: UUID) -> Optional[Report]:
    result = await db.execute(select(Report).where(Report.id == report_id))
    return result.scalar_one_or_none()


async def get_report_by_token(db: AsyncSession, token: str) -> Optional[Report]:
    result = await db.execute(
        select(Report).where(Report.email_verification_token == token)
    )
    return result.scalar_one_or_none()


async def update_report_status(
    db: AsyncSession,
    report_id: UUID,
    status: str,
    progress: int,
    error_message: Optional[str] = None,
) -> None:
    values: dict = {
        "status": status,
        "progress": progress,
        "updated_at": datetime.utcnow(),
    }
    if error_message is not None:
        values["error_message"] = error_message
    await db.execute(update(Report).where(Report.id == report_id).values(**values))
    await db.commit()


async def update_report_field(db: AsyncSession, report_id: UUID, **kwargs) -> None:
    kwargs["updated_at"] = datetime.utcnow()
    await db.execute(update(Report).where(Report.id == report_id).values(**kwargs))
    await db.commit()


async def log_event(
    db: AsyncSession,
    report_id: UUID,
    event_type: str,
    metadata: Optional[dict] = None,
) -> None:
    event = LeadEvent(
        report_id=report_id,
        event_type=event_type,
        metadata_json=metadata,
    )
    db.add(event)
    await db.commit()


async def find_recent_report_by_domain(
    db: AsyncSession,
    domain: str,
    not_older_than: datetime,
):
    """Срочный фикс 2.1: ищем свежий ЗАВЕРШЁННЫЙ отчёт по домену.

    Если есть — отдаём его (не запускаем дорогой pipeline заново).
    """
    if not domain:
        return None
    result = await db.execute(
        select(Report)
        .where(
            Report.domain_normalized == domain,
            Report.status == "completed",
            Report.created_at >= not_older_than,
        )
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def count_reports_since(
    db: AsyncSession,
    since: datetime,
    email: Optional[str] = None,
    ip: Optional[str] = None,
) -> int:
    """Срочный фикс 2.2: считает РЕАЛЬНЫЕ заявки за период по email или IP.

    Считаем все созданные отчёты (любой статус), кроме чисто отказных —
    важно ограничить именно создание (каждое = потенциальный запуск pipeline).
    """
    from sqlalchemy import func

    stmt = select(func.count(Report.id)).where(Report.created_at >= since)
    if email:
        stmt = stmt.where(Report.email == email)
    if ip:
        stmt = stmt.where(Report.ip_address == ip)
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def attach_email_to_report(db: AsyncSession, report_id: UUID, email: str) -> None:
    """При дедупе по домену: фиксируем, что этот email тоже запросил отчёт
    (через событие — основной email отчёта не перетираем)."""
    await log_event(db, report_id, "report_reused_for_email", metadata={"email": email})


async def delete_old_unverified_reports(db: AsyncSession, older_than: datetime) -> int:
    """Удаляет неверифицированные заявки старше указанной даты."""
    from sqlalchemy import delete
    result = await db.execute(
        delete(Report).where(
            Report.status == "pending_verification",
            Report.created_at < older_than,
        )
    )
    await db.commit()
    return result.rowcount
