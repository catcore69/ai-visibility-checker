import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Статус pipeline
    status = Column(String(50), default="pending", nullable=False, index=True)
    # pending_verification → verification_complete → niche_detection → competitor_discovery →
    # prompt_generation → polling_models → analyzing_responses → calculating_score →
    # generating_recommendations → building_pdf → awaiting_personal_note → sending_email →
    # completed / failed

    progress = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)

    # Входные данные
    url = Column(String(500), nullable=False)
    url_normalized = Column(String(500), nullable=False, index=True)
    canonical_key = Column(String(500), nullable=True)
    brand_name = Column(String(200), nullable=False)
    region = Column(String(100), nullable=False)
    email = Column(String(200), nullable=False, index=True)

    # Email верификация
    email_verification_token = Column(String(100), nullable=True, unique=True, index=True)
    email_verification_sent_at = Column(DateTime, nullable=True)
    email_verification_expires_at = Column(DateTime, nullable=True)
    email_verified_at = Column(DateTime, nullable=True)

    # Browser fingerprint
    browser_fingerprint = Column(String(200), nullable=True)

    # Этап 1 ТЗ: конкуренты, указанные клиентом в форме (опционально).
    # Если задано >=3 — pipeline берёт их вместо LLM-подбора.
    client_competitors = Column(JSONB, nullable=True)
    # Откуда взяты итоговые конкуренты: "client" / "mixed" / "llm".
    # Видно в PDF на странице методологии — снимает уязвимость
    # "вы выдумали моих конкурентов".
    competitors_source = Column(String(20), nullable=True)

    # Этап 1 ТЗ: фиксация согласий на ОПД (Закон РБ № 99-З).
    # Два РАЗДЕЛЬНЫХ согласия — общее и на трансграничную передачу.
    # Не nullable=False, чтобы старые отчёты не сломались, но в новых
    # обязательно проставляются на этапе POST /check.
    consent_personal_data_at = Column(DateTime, nullable=True)
    consent_cross_border_at = Column(DateTime, nullable=True)
    consent_ip = Column(String(45), nullable=True)  # IPv6-safe (45 символов)

    # Результаты pipeline (JSONB)
    niche_data = Column(JSONB, nullable=True)
    competitors = Column(JSONB, nullable=True)
    prompts = Column(JSONB, nullable=True)
    raw_responses = Column(JSONB, nullable=True)
    analysis = Column(JSONB, nullable=True)

    # Метрики
    visibility_score = Column(Integer, nullable=True)
    presence_rate = Column(Integer, nullable=True)
    share_of_voice = Column(Integer, nullable=True)
    sentiment_score = Column(Integer, nullable=True)

    # Рекомендации
    recommendations = Column(JSONB, nullable=True)

    # Личная заметка эксперта
    expert_note = Column(Text, nullable=True)

    # Файлы
    pdf_s3_key = Column(String(500), nullable=True)
    pdf_url = Column(String(1000), nullable=True)

    # Tracking
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    referrer = Column(String(500), nullable=True)
    utm_source = Column(String(100), nullable=True)
    utm_medium = Column(String(100), nullable=True)
    utm_campaign = Column(String(100), nullable=True)
