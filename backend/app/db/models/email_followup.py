"""Запланированный follow-up email (Этап 4.2 ТЗ).

Цепочка: day_3 / day_10 / day_30. Создаётся в send_report_ready,
сканируется и отправляется Celery Beat-задачей scan_pending_followups.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class EmailFollowup(Base):
    __tablename__ = "email_followups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    type = Column(String(20), nullable=False)  # "day_3" / "day_10" / "day_30"
    scheduled_at = Column(DateTime, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    cancelled_reason = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
