"""Единая точка «отчёт отправлен клиенту» (Этапы 4.2 + 4.4 ТЗ).

Отчёт может уходить клиенту из четырёх мест:
- pipeline.py (авто-отправка, если EXPERT_REVIEW_BEFORE_SEND=false);
- telegram_webhook «Отправить как есть»;
- telegram_webhook «Добавить заметку»;
- generate_report.auto_send_report_after_timeout (таймаут эксперта).

Чтобы во всех четырёх местах одинаково:
1) гарантировался unsubscribe_token,
2) отправлялось письмо,
3) запускалась follow-up цепочка,
4) создавалась сделка в Bitrix24,
— выносим это в один хелпер.
"""

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.logger import get_logger

logger = get_logger(__name__)


async def finalize_report_delivery(db: AsyncSession, report) -> bool:
    """Отправляет отчёт клиенту + follow-up цепочка + сделка Bitrix24.

    Возвращает True, если письмо ушло. Side-effects (followup, Bitrix)
    не влияют на возвращаемое значение — они best-effort.

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

    # 4. Сделка в Bitrix24 (стадия NEW)
    try:
        from app.integrations.bitrix24 import Bitrix24Client, STAGE_NEW
        bx = Bitrix24Client()
        await bx.upsert_deal(report, stage=STAGE_NEW)
    except Exception as exc:
        logger.error("finalize_bitrix_deal_failed", report_id=str(report.id), error=str(exc))

    return sent
