from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class ContactRequest(BaseModel):
    """Заявка на разговор с экспертом (Этап 5.2.3 ТЗ).

    Заполняется на странице ожидания / странице записи. Обязательны: имя,
    хотя бы один контакт (phone/telegram), оба согласия. Валидация деталей —
    в routes.add_contact (телефон, антиспам).
    """
    name: str
    phone: Optional[str] = None
    telegram: Optional[str] = None
    preferred_time: Optional[str] = None  # "утро" / "день" / "вечер" / "любое"
    consent_personal_data: bool = False
    consent_cross_border: bool = False


class CheckRequest(BaseModel):
    url: str
    brand_name: Optional[str] = None
    region: str = "Россия"
    email: EmailStr
    # Подсказка ниши от клиента из формы — приоритет над авто-детектом.
    # Принимаем под двумя именами (никакой alias-магии — оба явных поля).
    niche_hint: Optional[str] = Field(default=None, alias="niche")

    # Этап 1.1 ТЗ: клиент может сам указать своих конкурентов
    # (до 5 имён). Если задано >=3 — pipeline возьмёт их вместо LLM-подбора,
    # это сильно повышает релевантность для региональных/нишевых бизнесов.
    client_competitors: Optional[list[str]] = Field(default=None, max_length=5)

    # Этап 1.4 ТЗ: ДВА раздельных чекбокса согласия по Закону РБ № 99-З.
    # Оба обязательны — без них форма не должна отправляться.
    # Pydantic-валидатор ниже жёстко требует True.
    consent_personal_data: bool = False
    consent_cross_border: bool = False

    browser_fingerprint: Optional[str] = None
    turnstile_token: str = ""
    website_url_honeypot: str = ""  # Honeypot-поле
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None

    model_config = {"populate_by_name": True}

    @field_validator("url")
    @classmethod
    def _normalize_url(cls, v: str) -> str:
        """Только нормализация — реальная валидация (HEAD, blacklist)
        делается в routes.py через url_validator."""
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v

    @field_validator("client_competitors")
    @classmethod
    def _clean_competitors(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if not v:
            return None
        cleaned: list[str] = []
        for item in v:
            if not isinstance(item, str):
                continue
            name = item.strip()
            if not name:
                continue
            if len(name) > 100:
                name = name[:100]
            cleaned.append(name)
        return cleaned[:5] or None

    @field_validator("consent_personal_data")
    @classmethod
    def _require_consent_personal_data(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "Требуется согласие на обработку персональных данных."
            )
        return v

    @field_validator("consent_cross_border")
    @classmethod
    def _require_consent_cross_border(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "Требуется согласие на трансграничную передачу данных."
            )
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


class CompetitorRow(BaseModel):
    name: str
    is_client: bool
    score: int
    presence_rate: int
    sov: float
    models_found: int
    dominant_sentiment: str = "neutral"


class ModelBreakdownItem(BaseModel):
    model_name: str
    display_name: str
    short_name: str = ""
    presence_rate: int
    mentions: int
    prompts_tested: int
    avg_position: Optional[float] = None
    dominant_sentiment: str = "neutral"
    positive_count: int = 0
    neutral_count: int = 0
    negative_count: int = 0


class ModelListItem(BaseModel):
    model_name: str
    display_name: str
    short_name: str


class PromptMatrixCell(BaseModel):
    model_name: str
    mentioned: bool
    sentiment: Optional[str] = None
    position: Optional[int] = None
    error: Optional[bool] = None


class PromptMatrixRow(BaseModel):
    prompt: str
    cells: list[PromptMatrixCell]


class TopPromptItem(BaseModel):
    prompt: str
    mention_count: int
    avg_sentiment: Optional[str] = None


class BottomPromptItem(BaseModel):
    prompt: str
    mention_count: int
    competitor_count: int = 0


class Recommendation(BaseModel):
    title: str
    description: str
    effort: str = "medium"
    impact: Optional[str] = None
    action_items: list[str] = []
    priority: Optional[int] = None


class ScoreComponents(BaseModel):
    presence_rate_pct: int
    model_coverage_pct: int
    position_pct: int
    sentiment_pct: int


class SentimentBreakdown(BaseModel):
    positive: int
    neutral: int
    negative: int
    positive_pct: int
    neutral_pct: int
    negative_pct: int


class BestResponseItem(BaseModel):
    model_name: str
    model_display_name: str
    model_css_class: str = ""
    prompt: str
    response_excerpt: str
    brand_mentioned: bool
    position: Optional[int] = None
    sentiment: Optional[str] = None


class ReportFull(BaseModel):
    """Полная схема онлайн-отчёта (соответствует frontend/lib/api.ts → ReportFull)."""

    report_id: UUID
    brand_name: str
    website_url: str
    niche: str
    created_at: datetime

    visibility_score: int
    presence_rate: int
    verdict: str

    models_found: int
    models_total: int
    prompts_count: int

    sov_rank: Optional[int] = None
    competitors_count: int

    strong_models: list[str] = []
    weak_models: list[str] = []
    top_weakness: Optional[str] = None

    competitor_comparison: list[CompetitorRow] = []
    model_breakdown: list[ModelBreakdownItem] = []
    prompts_matrix: list[PromptMatrixRow] = []
    models_list: list[ModelListItem] = []
    top_prompts: list[TopPromptItem] = []
    bottom_prompts: list[BottomPromptItem] = []
    recommendations: list[Recommendation] = []
    expert_note: Optional[str] = None

    score_components: ScoreComponents
    sentiment_breakdown: Optional[SentimentBreakdown] = None
    best_responses: list[BestResponseItem] = []

    pdf_url: Optional[str] = None


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
