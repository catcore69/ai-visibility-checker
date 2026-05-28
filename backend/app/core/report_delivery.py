"""Единая точка «отчёт отправлен клиенту» (Этап 4.2 ТЗ).

Отчёт может уходить клиенту из четырёх мест:
- pipeline.py (авто-отправка, если EXPERT_REVIEW_BEFORE_SEND=false);
- telegram_webhook «Отправить как есть»;
- telegram_webhook «Добавить заметку»;
- generate_report.auto_send_report_after_timeout (таймаут эксперта).

Чтобы во всех четырёх местах одинаково:
1) гарантировался unsubscribe_token,
2) отправлялось письмо,
3) запускалась follow-up цепочка,
— выносим это в один хелпер.

Примечание: Bitrix24 убран из проекта — на бесплатном тарифе у него нет ни
API, ни виджета записи. CRM-роль выполняет Google Sheets + наша БД, заявки
на разговор собирает наша форма (см. /api/v1/report/{id}/contact).
"""

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger import get_logger

logger = get_logger(__name__)


async def finalize_report_delivery(db: AsyncSession, report) -> bool:
    """Отправляет отчёт клиенту + запускает follow-up цепочку.

    Возвращает True, если письмо ушло. Side-effect (followup-цепочка)
    не влияет на возвращаемое значение — он best-effort.

    Вызывать ПОСЛЕ того, как report.expert_note (если есть) уже сохранён.
    Статусы (sending_email / completed) выставляет вызывающий код —
    тут только доставка.
    """
    from app.config import settings
    from app.db.repositories.report_repo import get_report, update_report_field
    from app.email.sender import EmailSender

    # 1. Гарантируем unsubscribe_token (нужен для ссылок в письмах)
    if not getattr(report, "unsubscribe_token", None):
        token = secrets.token_urlsafe(32)
        await update_report_field(db, report.id, unsubscribe_token=token)
        refreshed = await get_report(db, report.id)
        if refreshed:
            report = refreshed

    # 2. Письмо «отчёт готов»
    sender = EmailSender(settings)
    sent = await sender.send_report_ready(report)

    # 3. Follow-up цепочка (день +3, +10, +30)
    try:
        from app.db.repositories.followup_repo import create_followup_chain
        await create_followup_chain(db, report.id)
    except Exception as exc:
        logger.error("finalize_followup_chain_failed", report_id=str(report.id), error=str(exc))

    return sent
