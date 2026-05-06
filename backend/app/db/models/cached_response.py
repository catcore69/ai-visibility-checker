import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class CachedLLMResponse(Base):
    """Кэш ответов LLM в БД (резервный, основной кэш — Redis)."""

    __tablename__ = "cached_llm_responses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cache_key = Column(String(500), unique=True, nullable=False, index=True)
    # Формат: "model:niche_hash:prompt_hash"
    response_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
