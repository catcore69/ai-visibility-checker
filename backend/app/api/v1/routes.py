import secrets
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from urllib.parse import quote
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
from app.utils.url_validator import validate_url as validate_client_url

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

    # Этап 1.2 ТЗ: валидация URL — формат, чёрный список агрегаторов, HEAD-проверка.
    # На клиенте тоже валидируем (input[type=url] + JS), но бэк — последняя линия защиты.
    is_valid_url, normalized_url, url_error = await validate_client_url(body.url)
    if not is_valid_url:
        raise HTTPException(400, url_error or "Адрес сайта не прошёл проверку.")
    # Используем нормализованный URL (с https://, без хвостов) во всём pipeline
    body_url = normalized_url

    brand_name = body.brand_name or extract_brand_from_url(body_url)

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
    domain_key, domain_brand_key = canonical_keys(body_url, brand_name)

    # Подсказка ниши от клиента — сохраняем в niche_data как user_hint,
    # чтобы pipeline (detect_niche) мог её учесть.
    niche_hint = (body.niche_hint or "").strip() or None
    niche_data_initial = {"user_hint": niche_hint} if niche_hint else None

    # Этап 1.4 ТЗ: фиксируем оба согласия с timestamp и IP клиента —
    # это юридическое доказательство для НЦЗПД РБ.
    now = datetime.utcnow()

    report = Report(
        url=body_url,
        url_normalized=normalize_url(body_url),
        canonical_key=domain_brand_key,
        brand_name=brand_name,
        region=body.region,
        email=str(body.email),
        status="pending_verification",
        email_verification_token=verification_token,
        email_verification_sent_at=now,
        email_verification_expires_at=expires_at,
        browser_fingerprint=body.browser_fingerprint,
        ip_address=ip,
        user_agent=request.headers.get("user-agent"),
        referrer=request.headers.get("referer"),
        utm_source=body.utm_source,
        utm_medium=body.utm_medium,
        utm_campaign=body.utm_campaign,
        niche_data=niche_data_initial,
        # Этап 1.1 — клиентские конкуренты
        client_competitors=body.client_competitors,
        # Этап 1.4 — согласия (Закон РБ № 99-З)
        consent_personal_data_at=now,
        consent_cross_border_at=now,
        consent_ip=ip,
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
    from app.celery_app import celery_app
    celery_app.send_task('app.tasks.generate_report.generate_report_task', args=[str(report.id)])

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
    """Полные данные отчёта для онлайн-просмотра.

    Доступен в статусах `completed` и `awaiting_personal_note` —
    чтобы эксперт мог открыть превью отчёта до отправки клиенту.
    """
    report = await get_report(db, report_id)
    if not report or report.status not in ("completed", "awaiting_personal_note"):
        raise HTTPException(404, "Отчёт не найден или ещё не готов.")

    await log_event(db, report_id, "report_viewed")

    analysis_data = report.analysis or {"results": [], "all_citations": []}
    analysis = _restore_analysis(analysis_data)

    from app.core.report_view import build_report_full_payload
    payload = build_report_full_payload(report, analysis)
    return ReportFull(**payload)


def _pdf_proxy_url(report_id: UUID) -> str:
    """URL для скачивания PDF через наш домен — без прямого выхода клиента на S3.

    Зачем: некоторые антивирусы (Avast, Касперский) флагят `s3.twcstorage.ru`
    как фишинг, а часть провайдеров режет этот хост. Поэтому отдаём клиенту
    ссылку на свой домен, а бэк сам стримит файл из S3.
    """
    base = settings.STUDIO_FULL_URL.rstrip("/")
    return f"{base}/api/v1/report/{report_id}/pdf/file"


@router.get("/report/{report_id}/pdf")
async def download_pdf(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """JSON-ответ с URL для скачивания PDF.

    Фронт (`frontend/lib/api.ts → getReportPdfUrl`) читает `data.url`.
    Раньше тут возвращался pre-signed S3-URL — теперь отдаём ссылку
    на наш домен (`/api/v1/report/{id}/pdf/file`), которая стримит файл.
    """
    report = await get_report(db, report_id)
    if not report or not report.pdf_s3_key:
        raise HTTPException(404, "PDF не готов.")

    url = _pdf_proxy_url(report_id)
    await log_event(db, report_id, "pdf_download_link_requested")

    # `expires_in` оставлен для обратной совместимости фронта;
    # фактически ссылка не истекает — это наш собственный endpoint.
    return {"url": url, "download_url": url, "expires_in": 3600}


@router.get("/report/{report_id}/pdf/file")
async def stream_pdf(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Стримит PDF клиенту через наш домен.

    Backend сам берёт файл из S3 и отдаёт его браузеру с `Content-Disposition:
    attachment`. Клиент видит в адресной строке `catcore.ru`, а не S3-домен —
    антивирусы и провайдеры не блокируют.
    """
    report = await get_report(db, report_id)
    if not report or not report.pdf_s3_key:
        raise HTTPException(404, "PDF не готов.")

    from app.storage.s3_client import S3Client
    import asyncio
    s3 = S3Client()

    try:
        obj = await asyncio.to_thread(
            s3._client.get_object,
            Bucket=s3.bucket,
            Key=report.pdf_s3_key,
        )
    except Exception as exc:
        logger.error("pdf_stream_s3_error", report_id=str(report_id), error=str(exc))
        raise HTTPException(502, "Не удалось получить файл из хранилища.")

    body = obj["Body"]  # botocore StreamingBody — sync iterator

    def iter_chunks(chunk_size: int = 64 * 1024):
        try:
            while True:
                chunk = body.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                body.close()
            except Exception:
                pass

    safe_brand = "".join(c for c in (report.brand_name or "report") if c.isalnum() or c in "-_") or "report"
    filename = f"{safe_brand}-AI-Visibility.pdf"
    filename_utf8 = quote(filename)

    headers = {
        # ASCII fallback + UTF-8 для современных браузеров
        "Content-Disposition": f'attachment; filename="report.pdf"; filename*=UTF-8\'\'{filename_utf8}',
        "Cache-Control": "private, max-age=0, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if obj.get("ContentLength"):
        headers["Content-Length"] = str(obj["ContentLength"])

    await log_event(db, report_id, "pdf_downloaded")

    return StreamingResponse(
        iter_chunks(),
        media_type="application/pdf",
        headers=headers,
    )


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

    # Этап 4.2 ТЗ: клик по CTA — горячий лид — отменяет follow-up цепочку.
    # Триггеры отмены: call_scheduled (Bitrix24 webhook, Этап 4.4), checklist_downloaded.
    try:
        from app.db.repositories.followup_repo import cancel_followups_for_report
        reason = "call_scheduled" if body.cta_type in ("call", "booking", "telegram") else "cta_clicked"
        await cancel_followups_for_report(db, report_id, reason)
    except Exception as exc:
        logger.warning("followup_cancel_on_cta_failed", error=str(exc))

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


@router.get("/report/{report_id}/unsubscribe")
async def unsubscribe(
    report_id: UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Этап 4.2 ТЗ: отписка от follow-up писем по ссылке из email.

    Сверяем токен (защита от чужих кликов — без токена URL никто не угадает).
    Помечаем report.unsubscribed_at + отменяем все pending follow-ups.
    Возвращаем простую HTML-страницу с подтверждением.
    """
    from fastapi.responses import HTMLResponse

    report = await get_report(db, report_id)
    if not report or not token or token != (report.unsubscribe_token or ""):
        raise HTTPException(404, "Ссылка недействительна.")

    if not report.unsubscribed_at:
        await update_report_field(db, report_id, unsubscribed_at=datetime.utcnow())

    try:
        from app.db.repositories.followup_repo import cancel_followups_for_report
        await cancel_followups_for_report(db, report_id, "user_unsubscribed")
    except Exception as exc:
        logger.warning("followup_cancel_on_unsubscribe_failed", error=str(exc))

    await log_event(db, report_id, "email_unsubscribed")

    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8"><title>Отписка — CatCore</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Arial, sans-serif; background: #0E0F12;
          color: #E6E8EC; margin: 0; padding: 80px 20px; text-align: center; }}
  .card {{ max-width: 480px; margin: 0 auto; background: #1B1D22;
           border: 1px solid #2F333B; border-radius: 16px; padding: 40px 32px; }}
  h1 {{ font-size: 24px; margin: 0 0 16px; color: #FFFFFF; }}
  p  {{ font-size: 15px; color: #8A8F99; line-height: 1.55; margin: 0 0 16px; }}
  a  {{ color: #A63D3D; text-decoration: none; }}
</style></head><body>
  <div class="card">
    <h1>Готово, отписали</h1>
    <p>Больше не отправим вам ни одного письма по этому отчёту.</p>
    <p>Если передумаете — отчёт всегда открывается здесь:<br>
       <a href="{settings.STUDIO_FULL_URL}/otchet/{report_id}">{settings.STUDIO_FULL_URL}/otchet/{report_id}</a>
    </p>
  </div>
</body></html>"""
    return HTMLResponse(content=html, status_code=200)


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


@router.post("/telegram/webhook/{secret}")
async def telegram_webhook(
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Webhook от Telegram: обрабатываем callback_query и команды эксперта.

    URL: POST /api/v1/telegram/webhook/{secret}
    secret = sha256(TELEGRAM_BOT_TOKEN)[:32] — см. integrations/telegram_webhook.py.
    """
    from app.integrations.telegram_webhook import expected_webhook_secret, handle_update

    expected = expected_webhook_secret()
    if not expected or secret != expected:
        raise HTTPException(403, "Invalid webhook secret")

    try:
        update = await request.json()
    except Exception:
        update = {}

    try:
        await handle_update(update, db)
    except Exception as exc:
        logger.error("telegram_webhook_handler_failed", error=repr(exc), error_type=type(exc).__name__)
        # Telegram считает любой не-200 за повтор. Отдаём 200, чтобы не зациклить.
    return {"ok": True}


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
