"""Кеш промптов по нише — детерминированный, чтобы отчёты в одной нише
давали сравнимые цифры (без temperature=0.7-шума)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class NichePromptTemplate(Base):
    __tablename__ = "niche_prompt_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Детерминированный ключ slugify("{category}_{subcategory}_{region}_{target_audience}")
    niche_key = Column(Text, nullable=False, unique=True)
    category = Column(Text, nullable=False, index=True)
    subcategory = Column(Text, nullable=True)
    region = Column(Text, nullable=True)
    target_audience = Column(Text, nullable=True)
    # Массив из 10 промптов: 4 рекомендательных, 3 сравнительных,
    # 2 проблемных, 1 транзакционный.
    prompts = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
