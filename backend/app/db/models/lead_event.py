import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class LeadEvent(Base):
    """Воронка событий: открыл отчёт, скачал PDF, кликнул CTA и т.д."""

    __tablename__ = "lead_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    # report_started_pending_verification, email_verified, report_completed,
    # report_viewed, pdf_downloaded, cta_clicked_hot_lead, followup_day_2_sent, followup_day_7_sent
    metadata_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
