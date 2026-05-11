import secrets
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_db, get_redis, verify_internal_token
from app.api.v1.schemas import (
    CheckRequest,
    CheckResponse,
    CTAClickRequest,
    ExpertActionRequest,
    ReportFull,
    ReportStatusResponse,
)
from app.cache.redis_cache import RedisCache
from app.config import settings
from app.core.pipeline import PROGRESS_MESSAGES
from app.core.scorer import compare_with_competitors, get_model_breakdown, get_top_sources
from app.core.analyzer import Analysis
from app.db.models.report import Report
from app.db.repositories.report_repo import (
    create_report,
    get_report,
    get_report_by_token,
    log_event,
    update_report_field,
    update_report_status,
)
from app.utils.logger import get_logger
from app.utils.rate_limiter import check_can_create_report, get_queue_position
from app.utils.url_normalizer import canonical_keys, extract_brand_from_url, mask_email, normalize_url

logger = get_logger(__name__)

router = APIRouter()


@router.post("/check", response_model=CheckResponse)
async def start_check(
    request: Request,
    body: CheckRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisCache = Depends(get_redis),
) -> CheckResponse:
    """Принимает заявку, отправляет email верификации. Pipeline стартует только после клика."""

    ip = request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.client.host if request.client else "0.0.0.0")
    brand_name = body.brand_name or extract_brand_from_url(body.url)

    # Многослойная проверка защиты от абуза
  #  can_create, reason = await check_can_create_report(
    #    redis=redis,
      #  email=str(body.email),
        #url=body.url,
        #brand=brand_name,
        #fingerprint=body.browser_fingerprint,
        #ip=ip,
        #honeypot_value=body.website_url_honeypot,
        #turnstile_token=body.turnstile_token,
    #)
    #if not can_create:
      #  logger.warning("rate_limit_hit", reason=reason, ip=ip, email=str(body.email))
        #raise HTTPException(429, f"Слишком много запросов: {reason}")
# Временно разрешаем все запросы
    can_create = True
    reason = "disabled_bypass" # Временно разрешаем все запросы

    verification_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=24)
    domain_key, domain_brand_key = canonical_keys(body.url, brand_name)

    report = Report(
        url=body.url,
        url_normalized=normalize_url(body.url),
        canonical_key=domain_brand_key,
        brand_name=brand_name,
        region=body.region,
        email=str(body.email),
        status="pending_verification",
        email_verification_token=verification_token,
        email_verification_sent_at=datetime.utcnow(),
        email_verification_expires_at=expires_at,
        browser_fingerprint=body.browser_fingerprint,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
        utm_source=body.utm_source,
        utm_medium=body.utm_medium,
        utm_campaign=body.utm_campaign,
    )
    await create_report(db, report)

    # Email верификации
    from app.email.sender import EmailSender
    email_sender = EmailSender(settings)
    await email_sender.send_verification(report)

    # Уведомление в Telegram
    from app.integrations.telegram import TelegramNotifier
    telegram = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)
    await telegram.notify_pending_verification(report)

    # CRM
    try:
        from app.integrations.google_sheets import GoogleSheetsCRM
        crm = GoogleSheetsCRM(settings.GOOGLE_SHEETS_CREDENTIALS_PATH, settings.GOOGLE_SHEETS_SPREADSHEET_ID)
        await crm.add_lead(report, "report_started_pending_verification")
    except Exception as exc:
        logger.error("crm_error", error=str(exc))

    await log_event(db, report.id, "report_started_pending_verification")

    return CheckResponse(
        report_id=report.id,
        status="pending_verification",
        message="Проверьте email. Мы отправили письмо с ссылкой для подтверждения.",
        email=mask_email(str(body.email)),
    )


@router.get("/verify/{token}")
async def verify_email_and_start(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Email-верификация. Только после этого запускается pipeline."""
    report = await get_report_by_token(db, token)

    if not report:
        raise HTTPException(404, "Ссылка недействительна или уже использована.")

    if report.email_verification_expires_at and report.email_verification_expires_at < datetime.utcnow():
        raise HTTPException(410, "Ссылка истекла. Отправьте новый запрос.")

    if report.email_verified_at:
        return RedirectResponse(f"{settings.STUDIO_FULL_URL}/otchet/{report.id}/status")

    # Верифицируем email
    await update_report_field(
        db,
        report.id,
        email_verified_at=datetime.utcnow(),
        status="verification_complete",
    )

    # ЗАПУСКАЕМ pipeline
    from app.tasks.generate_report import generate_report_task
    generate_report_task.delay(str(report.id))

    # Уведомления
    from app.integrations.telegram import TelegramNotifier
    from app.integrations.google_sheets import GoogleSheetsCRM
    telegram = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)
    await telegram.notify_pipeline_started(report)

    try:
        crm = GoogleSheetsCRM(settings.GOOGLE_SHEETS_CREDENTIALS_PATH, settings.GOOGLE_SHEETS_SPREADSHEET_ID)
        await crm.add_lead(report, "email_verified_pipeline_started")
    except Exception:
        pass

    await log_event(db, report.id, "email_verified")

    return RedirectResponse(f"{settings.STUDIO_FULL_URL}/otchet/{report.id}/status")


@router.get("/report/{report_id}/status", response_model=ReportStatusResponse)
async def get_report_status(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisCache = Depends(get_redis),
) -> ReportStatusResponse:
    """Polling-эндпоинт для прогресс-бара на фронте."""
    report = await get_report(db, report_id)
    if not report:
        raise HTTPException(404, "Отчёт не найден.")

    if report.status == "pending_verification":
        return ReportStatusResponse(
            id=report.id,
            status="pending_verification",
            progress=0,
            message="Ожидание подтверждения email. Проверьте почту и перейдите по ссылке.",
            completed=False,
            failed=False,
        )

    queue_position = None
    estimated_wait = None
    if report.status in ("pending", "verification_complete"):
        queue_position = await get_queue_position(redis)
        estimated_wait = queue_position * 180 if queue_position else None

    return ReportStatusResponse(
        id=report.id,
        status=report.status,
        progress=report.progress,
        message=PROGRESS_MESSAGES.get(report.status, ""),
        completed=report.status == "completed",
        failed=report.status == "failed",
        error=report.error_message,
        queue_position=queue_position,
        estimated_wait_seconds=estimated_wait,
    )


@router.get("/report/{report_id}", response_model=ReportFull)
async def get_full_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ReportFull:
    """Полные данные отчёта для онлайн-просмотра."""
    report = await get_report(db, report_id)
    if not report or report.status != "completed":
        raise HTTPException(404, "Отчёт не найден или ещё не готов.")

    await log_event(db, report_id, "report_viewed")

    # Восстанавливаем Analysis из JSON
    analysis_data = report.analysis or {"results": [], "all_citations": []}
    analysis = _restore_analysis(analysis_data)

    competitors = report.competitors or []
    all_brands = [report.brand_name] + competitors

    comparison = compare_with_competitors(analysis, report.brand_name, all_brands)
    model_breakdown = get_model_breakdown(analysis, report.brand_name)
    top_sources = get_top_sources(analysis)

    return ReportFull(
        id=report.id,
        brand_name=report.brand_name,
        url=report.url,
        region=report.region,
        created_at=report.created_at,
        visibility_score=report.visibility_score or 0,
        presence_rate=report.presence_rate or 0,
        share_of_voice=float(report.share_of_voice or 0),
        niche=report.niche_data or {},
        competitors=competitors,
        comparison=[
            {
                "brand_name": c["brand_name"],
                "score": c["score"],
                "presence_rate": c["presence_rate"],
                "share_of_voice": c["share_of_voice"],
                "is_client": c["is_client"],
            }
            for c in comparison
        ],
        model_breakdown=model_breakdown,
        recommendations=[
            {
                "priority": r.get("priority", 1),
                "title": r.get("title", ""),
                "description": r.get("description", ""),
                "expected_impact": r.get("expected_impact", ""),
                "effort": r.get("effort", "medium"),
            }
            for r in (report.recommendations or [])
        ],
        pdf_url=report.pdf_url,
        top_sources=top_sources[:10],
        expert_note=report.expert_note,
    )


@router.get("/report/{report_id}/pdf")
async def download_pdf(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pre-signed URL на PDF в S3 (1 час)."""
    report = await get_report(db, report_id)
    if not report or not report.pdf_s3_key:
        raise HTTPException(404, "PDF не готов.")

    from app.storage.s3_client import S3Client
    s3 = S3Client()
    url = await s3.generate_presigned_url(report.pdf_s3_key, expires_in=3600)

    await log_event(db, report_id, "pdf_downloaded")

    return {"download_url": url, "expires_in": 3600}


@router.post("/report/{report_id}/cta")
async def cta_click(
    report_id: UUID,
    body: CTAClickRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Клик по CTA — горячий лид."""
    report = await get_report(db, report_id)
    if not report:
        raise HTTPException(404)

    metadata = {
        "cta_type": body.cta_type,
        "telegram": body.telegram,
        "comment": body.comment,
    }
    await log_event(db, report_id, "cta_clicked_hot_lead", metadata=metadata)

    from app.integrations.telegram import TelegramNotifier
    from app.integrations.google_sheets import GoogleSheetsCRM
    telegram = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)
    await telegram.notify_cta_click(report, metadata)

    try:
        crm = GoogleSheetsCRM(settings.GOOGLE_SHEETS_CREDENTIALS_PATH, settings.GOOGLE_SHEETS_SPREADSHEET_ID)
        await crm.add_lead(report, "cta_clicked_hot_lead")
    except Exception:
        pass

    return {"received": True}


@router.post("/check/{report_id}/resend-email")
async def resend_verification_email(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisCache = Depends(get_redis),
) -> dict:
    """Повторная отправка email верификации (не чаще 1 раза в 60 секунд)."""
    resend_key = f"resend:{report_id}"
    if await redis.exists(resend_key):
        raise HTTPException(429, "Подождите 60 секунд перед повторной отправкой.")

    report = await get_report(db, report_id)
    if not report or report.status != "pending_verification":
        raise HTTPException(404, "Заявка не найдена или уже подтверждена.")

    from app.email.sender import EmailSender
    sender = EmailSender(settings)
    await sender.send_verification(report)

    await redis.set(resend_key, "1", ttl=60)
    return {"sent": True}


@router.post("/internal/report/{report_id}/action", dependencies=[Depends(verify_internal_token)])
async def expert_action(
    report_id: UUID,
    body: ExpertActionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Эндпоинт для callback от Telegram-бота эксперта."""
    report = await get_report(db, report_id)
    if not report:
        raise HTTPException(404)

    from app.email.sender import EmailSender
    from app.integrations.telegram import TelegramNotifier
    sender = EmailSender(settings)
    telegram = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)

    if body.action == "add_note" and body.note:
        await update_report_field(db, report_id, expert_note=body.note)
        report.expert_note = body.note
        await update_report_status(db, report_id, "sending_email", progress=99)
        await sender.send_report_ready(report)
        await update_report_status(db, report_id, "completed", progress=100)
        await telegram.notify_report_completed(report)

    elif body.action == "send_as_is":
        await update_report_status(db, report_id, "sending_email", progress=99)
        await sender.send_report_ready(report)
        await update_report_status(db, report_id, "completed", progress=100)
        await telegram.notify_report_completed(report)

    elif body.action == "hold":
        await update_report_field(db, report_id, status="held_by_expert")

    return {"ok": True}


def _restore_analysis(data: dict) -> Analysis:
    """Восстанавливает объект Analysis из JSONB."""
    from app.core.analyzer import Analysis, MentionResult
    analysis = Analysis()
    for r in data.get("results", []):
        analysis.results.append(
            MentionResult(
                model_name=r.get("model_name", ""),
                prompt=r.get("prompt", ""),
                brand_name=r.get("brand_name", ""),
                mentioned=r.get("mentioned", False),
                position=r.get("position", 0),
                sentiment=r.get("sentiment", "neutral"),
                context=r.get("context", ""),
                is_recommendation=r.get("is_recommendation", False),
                citations=r.get("citations", []),
            )
        )
    analysis.all_citations = data.get("all_citations", [])
    return analysis
