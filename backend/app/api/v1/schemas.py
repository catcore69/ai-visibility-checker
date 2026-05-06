from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, HttpUrl, field_validator


class CheckRequest(BaseModel):
    url: str
    brand_name: Optional[str] = None
    region: str = "Россия"
    email: EmailStr
    browser_fingerprint: Optional[str] = None
    turnstile_token: str = ""
    website_url_honeypot: str = ""  # Honeypot-поле
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v


class CheckResponse(BaseModel):
    report_id: UUID
    status: str
    message: str
    email: str  # маскированный


class ReportStatusResponse(BaseModel):
    id: UUID
    status: str
    progress: int
    message: str
    completed: bool
    failed: bool
    error: Optional[str] = None
    queue_position: Optional[int] = None
    estimated_wait_seconds: Optional[int] = None


class BrandMention(BaseModel):
    brand_name: str
    score: int
    presence_rate: int
    share_of_voice: float
    is_client: bool


class ModelBreakdownItem(BaseModel):
    model_name: str
    mention_rate: int
    avg_position: float
    dominant_sentiment: str
    total_prompts: int
    mentioned_count: int


class Recommendation(BaseModel):
    priority: int
    title: str
    description: str
    expected_impact: str
    effort: str


class ReportFull(BaseModel):
    id: UUID
    brand_name: str
    url: str
    region: str
    created_at: datetime
    visibility_score: int
    presence_rate: int
    share_of_voice: float
    niche: dict[str, Any]
    competitors: list[str]
    comparison: list[BrandMention]
    model_breakdown: list[ModelBreakdownItem]
    recommendations: list[Recommendation]
    pdf_url: Optional[str] = None
    top_sources: list[str]
    expert_note: Optional[str] = None


class CTAClickRequest(BaseModel):
    cta_type: str  # "consultation", "audit", "callback"
    telegram: Optional[str] = None
    comment: Optional[str] = None


class ResendEmailRequest(BaseModel):
    report_id: UUID


class ExpertActionRequest(BaseModel):
    action: str  # "send_as_is", "add_note", "hold"
    note: Optional[str] = None
    auth_token: str
