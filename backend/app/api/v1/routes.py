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
    ContactRequest,
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
    attach_email_to_report,
    count_reports_since,
    create_report,
    find_recent_report_by_domain,
    get_report,
    get_report_by_token,
    log_event,
    update_report_field,
    update_report_status,
)
from app.utils.logger import get_logger
from app.utils.rate_limiter import get_queue_position, verify_turnstile
from app.utils.url_normalizer import (
    canonical_keys,
    extract_brand_from_url,
    extract_root_domain,
    mask_email,
    normalize_url,
)
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

    # ── ЗАЩИТА ОТ АБУЗА (порядок по срочному ТЗ) ──────────────────────────────

    # 1. Turnstile. Проверяем, только если задан секрет (иначе dev/без капчи).
    if settings.TURNSTILE_SECRET_KEY:
        if not await verify_turnstile(body.turnstile_token, ip):
            logger.warning("turnstile_failed", ip=ip)
            raise HTTPException(403, "Проверка «вы не робот» не пройдена. Обновите страницу.")

    # 2. Honeypot — тихо притворяемся успехом, ничего не делаем.
    if body.website_url_honeypot:
        logger.warning("honeypot_triggered", ip=ip)
        return CheckResponse(
            report_id=__import__("uuid").uuid4(),
            status="pending_verification",
            message="Проверьте email.",
            email=mask_email(str(body.email)),
        )

    # 3. Валидация URL — формат, чёрный список агрегаторов, HEAD-проверка.
    is_valid_url, normalized_url, url_error = await validate_client_url(body.url)
    if not is_valid_url:
        raise HTTPException(400, url_error or "Адрес сайта не прошёл проверку.")
    body_url = normalized_url
    brand_name = body.brand_name or extract_brand_from_url(body_url)
    domain_normalized = extract_root_domain(body_url)

    # 4. Лимиты на РЕАЛЬНЫЕ запуски (защита денег на API).
    now = datetime.utcnow()
    email_str = str(body.email)
    cnt_email_day = await count_reports_since(db, now - timedelta(days=1), email=email_str)
    if cnt_email_day >= settings.MAX_ANALYSES_PER_EMAIL_PER_DAY:
        raise HTTPException(429, "С этого email сегодня уже создан максимум отчётов. Попробуйте завтра или напишите нам.")
    cnt_ip_hour = await count_reports_since(db, now - timedelta(hours=1), ip=ip)
    if cnt_ip_hour >= settings.MAX_ANALYSES_PER_IP_PER_HOUR:
        raise HTTPException(429, "Слишком много запросов. Подождите час.")
    cnt_ip_day = await count_reports_since(db, now - timedelta(days=1), ip=ip)
    if cnt_ip_day >= settings.MAX_ANALYSES_PER_IP_PER_DAY:
        raise HTTPException(429, "Достигнут дневной лимит запросов с вашего адреса.")

    # 5. Дедуп по домену — отдаём готовый отчёт, не запускаем pipeline заново.
    reuse_since = now - timedelta(days=settings.REPORT_REUSE_DAYS)
    existing = await find_recent_report_by_domain(db, domain_normalized, reuse_since)
    if existing:
        await attach_email_to_report(db, existing.id, email_str)
        # Шлём готовый отчёт НА ВВЕДЁННЫЙ адрес (не на почту старого отчёта!),
        # без пересчёта и без верификации — ничего дорогого не запускаем.
        try:
            from app.email.sender import EmailSender
            await EmailSender(settings).send_report_ready(existing, override_email=email_str)
        except Exception as exc:
            logger.error("reuse_send_failed", error=str(exc))
        logger.info("report_reused_by_domain", domain=domain_normalized, report_id=str(existing.id))
        return CheckResponse(
            report_id=existing.id,
            status="completed",
            message="Свежий отчёт по этому сайту уже готов — отправили его на ваш email.",
            email=mask_email(email_str),
        )

    verification_token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=24)
    domain_key, domain_brand_key = canonical_keys(body_url, brand_name)

    # Подсказка ниши от клиента — сохраняем в niche_data как user_hint,
    # чтобы pipeline (detect_niche) мог её учесть.
    niche_hint = (body.niche_hint or "").strip() or None
    niche_data_initial = {"user_hint": niche_hint} if niche_hint else None

    # Этап 1.4 ТЗ: фиксируем оба согласия с timestamp и IP клиента (Закон РБ № 99-З).
    report = Report(
        url=body_url,
        url_normalized=normalize_url(body_url),
        domain_normalized=domain_normalized,
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


@router.post("/report/{report_id}/contact")
async def add_contact(
    report_id: UUID,
    body: ContactRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Заявка на разговор с экспертом (Этап 5.2.3 ТЗ).

    Заменяет виджет Bitrix24 (его нет на бесплатном тарифе). Клиент оставляет
    имя + телефон/Telegram + удобное время + два согласия. Мы:
    - валидируем и сохраняем контакт в reports;
    - помечаем spam_suspect при мусорном телефоне;
    - если не спам — шлём эксперту Telegram «🔥 Горячий лид»;
    - отменяем follow-up цепочку (клиент уже на связи);
    - логируем в Google Sheets.
    Эксперт перезванивает вручную (календарного виджета нет — есть «удобное время»).
    """
    from app.utils.phone import is_suspicious_phone, normalize_phone

    report = await get_report(db, report_id)
    if not report:
        raise HTTPException(404, "Отчёт не найден.")

    name = (body.name or "").strip()
    if len(name) < 2:
        raise HTTPException(400, "Укажите имя (минимум 2 символа).")
    if not (body.phone or body.telegram):
        raise HTTPException(400, "Укажите телефон или Telegram.")
    if not body.consent_personal_data:
        raise HTTPException(400, "Требуется согласие на обработку персональных данных.")
    if not body.consent_cross_border:
        raise HTTPException(400, "Требуется согласие на трансграничную передачу данных.")

    ip = request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.client.host if request.client else "")

    phone_norm = None
    is_spam = False
    if body.phone:
        phone_norm, valid = normalize_phone(body.phone)
        if not valid:
            raise HTTPException(400, "Похоже, формат телефона неверный — проверьте, пожалуйста.")
        is_spam = is_suspicious_phone(phone_norm)

    telegram = (body.telegram or "").strip() or None
    if telegram and not telegram.startswith("@"):
        telegram = "@" + telegram.lstrip("@")

    now = datetime.utcnow()
    await update_report_field(
        db,
        report_id,
        client_name=name,
        client_phone=phone_norm,
        client_telegram=telegram,
        preferred_call_time=(body.preferred_time or "любое"),
        contact_given_at=now,
        contact_consent_personal_data_at=now,
        contact_consent_cross_border_at=now,
        contact_consent_ip=ip,
        spam_suspect=is_spam,
    )
    report = await get_report(db, report_id)

    await log_event(db, report_id, "contact_given", metadata={
        "preferred_time": body.preferred_time,
        "has_phone": bool(phone_norm),
        "has_telegram": bool(telegram),
        "spam_suspect": is_spam,
    })

    # Отменяем follow-up — клиент уже на связи.
    try:
        from app.db.repositories.followup_repo import cancel_followups_for_report
        await cancel_followups_for_report(db, report_id, "contact_given")
    except Exception as exc:
        logger.warning("contact_cancel_followups_failed", error=str(exc))

    # Telegram «Горячий лид» — только если не подозрение на спам.
    if not is_spam:
        from app.integrations.telegram import TelegramNotifier
        telegram_notifier = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)
        try:
            await telegram_notifier.notify_hot_lead(report, {
                "name": name,
                "phone": phone_norm,
                "telegram": telegram,
                "preferred_time": body.preferred_time or "любое",
            })
        except Exception as exc:
            logger.error("notify_hot_lead_failed", error=repr(exc))

    # Google Sheets — фиксируем горячий лид.
    try:
        from app.integrations.google_sheets import GoogleSheetsCRM
        crm = GoogleSheetsCRM(settings.GOOGLE_SHEETS_CREDENTIALS_PATH, settings.GOOGLE_SHEETS_SPREADSHEET_ID)
        await crm.add_lead(report, "contact_given_hot_lead")
    except Exception:
        pass

    return {"status": "ok", "spam_suspect": is_spam}


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


@router.get("/internal/metrics", dependencies=[Depends(verify_internal_token)])
async def funnel_metrics(
    db: AsyncSession = Depends(get_db),
    days: int = 90,
) -> dict:
    """Метрики воронки (Этап 6 ТЗ).

    Агрегирует reports + lead_events за последние `days` дней в счётчики этапов
    и конверсии. Защищено internal-токеном. Источник данных для дашборда
    фаундера (можно дёргать из Google Sheets / Looker / руками).
    """
    from datetime import timedelta
    from sqlalchemy import func, select as _select
    from app.db.models.lead_event import LeadEvent

    since = datetime.utcnow() - timedelta(days=max(1, days))

    # --- Счётчики по reports ---
    async def _count_reports(*conds) -> int:
        stmt = _select(func.count(Report.id)).where(Report.created_at >= since, *conds)
        return int((await db.execute(stmt)).scalar() or 0)

    total = await _count_reports()
    verified = await _count_reports(Report.email_verified_at.isnot(None))
    completed = await _count_reports(Report.status == "completed")
    contact_given = await _count_reports(Report.contact_given_at.isnot(None))
    unsubscribed = await _count_reports(Report.unsubscribed_at.isnot(None))

    # --- Уникальные report_id по типам событий ---
    async def _distinct_events(event_types: list[str]) -> int:
        stmt = _select(func.count(func.distinct(LeadEvent.report_id))).where(
            LeadEvent.created_at >= since,
            LeadEvent.event_type.in_(event_types),
        )
        return int((await db.execute(stmt)).scalar() or 0)

    report_viewed = await _distinct_events(["report_viewed"])
    pdf_downloaded = await _distinct_events(["pdf_downloaded"])
    cta_clicked = await _distinct_events(["cta_clicked_hot_lead", "contact_given"])

    def _rate(part: int, whole: int) -> float:
        return round(part / whole * 100, 1) if whole else 0.0

    return {
        "period_days": days,
        "funnel": {
            "reports_total": total,
            "email_verified": verified,
            "report_completed": completed,
            "report_viewed": report_viewed,
            "pdf_downloaded": pdf_downloaded,
            "cta_clicked": cta_clicked,
            "contact_given": contact_given,
            "unsubscribed": unsubscribed,
        },
        "conversion_rates_pct": {
            # Из главных метрик ТЗ (часть 6).
            "verify_rate": _rate(verified, total),
            "complete_rate": _rate(completed, verified),
            "pdf_download_rate": _rate(pdf_downloaded, completed),
            "cta_click_rate": _rate(cta_clicked, completed),
            "contact_given_rate": _rate(contact_given, completed),
            "lead_to_contact_rate": _rate(contact_given, total),
        },
    }


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
