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
