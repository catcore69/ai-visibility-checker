from uuid import UUID

import traceback
import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _proxy() -> str | None:
    """Опциональный прокси для api.telegram.org (если RU/BY-провайдер режет)."""
    return settings.TELEGRAM_PROXY_URL or None


class TelegramNotifier:
    def __init__(self, bot_token: str, notify_chat_id: str):
        self.bot_token = bot_token
        self.notify_chat_id = notify_chat_id
        # Используем настраиваемую базу (по умолчанию api.telegram.org),
        # чтобы можно было пустить через Cloudflare Worker relay.
        base = (settings.TELEGRAM_API_BASE or "https://api.telegram.org").rstrip("/")
        self.api_url = f"{base}/bot{bot_token}"

    async def _send(self, message: str, parse_mode: str = "HTML") -> None:
        if not self.bot_token or not self.notify_chat_id:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0, proxy=_proxy()) as client:
                await client.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.notify_chat_id,
                        "text": message,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
        except Exception as exc:
            logger.error("telegram_notify_failed", error=repr(exc), error_type=type(exc).__name__, tb=traceback.format_exc()[:500])

    async def _send_with_keyboard(self, message: str, keyboard: list) -> None:
        """Отправляет сообщение с inline-кнопками."""
        if not self.bot_token or not self.notify_chat_id:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0, proxy=_proxy()) as client:
                await client.post(
                    f"{self.api_url}/sendMessage",
                    json={
                        "chat_id": self.notify_chat_id,
                        "text": message,
                        "parse_mode": "HTML",
                        "reply_markup": {"inline_keyboard": keyboard},
                        "disable_web_page_preview": True,
                    },
                )
        except Exception as exc:
            logger.error("telegram_keyboard_failed", error=repr(exc), error_type=type(exc).__name__, tb=traceback.format_exc()[:500])

    async def notify_pending_verification(self, report) -> None:
        await self._send(
            f"🟡 <b>Новая заявка</b> (ждёт верификации email)\n\n"
            f"📧 {report.email}\n"
            f"🌐 {report.url}\n"
            f"🏢 {report.brand_name}\n"
            f"🌍 {report.region}\n\n"
            f"Источник: {report.utm_source or 'прямой'}"
        )

    async def notify_pipeline_started(self, report) -> None:
        await self._send(
            f"🟢 <b>Email подтверждён, генерация запущена</b>\n\n"
            f"📧 {report.email}\n"
            f"🏢 {report.brand_name}"
        )

    async def notify_report_ready_for_review(self, report, score: int) -> None:
        """Эксперту: отчёт готов, выберите действие.

        Этап 4.3 ТЗ — Quality flags + классификация горячести лида:
        - 🟢 competitors_source=client (клиент сам указал, релевантность высокая)
        - 🟡 mixed (частично клиент)
        - 🔴 llm (риск выдуманных конкурентов)
        - hot/warm/cold по Score и наличию контактов.
        """
        from app.config import settings
        score_emoji = "🔴" if score < 30 else "🟡" if score < 60 else "🟢"

        # Quality flag по источнику конкурентов
        cs = getattr(report, "competitors_source", None) or "llm"
        if cs == "client":
            cs_flag = "🟢 указаны клиентом"
        elif cs == "mixed":
            cs_flag = "🟡 частично клиент"
        else:
            cs_flag = "🔴 полностью LLM (проверить!)"

        # Site analysis flag
        site_ok = bool(getattr(report, "client_site_analysis", None) and report.client_site_analysis.get("fetched"))
        site_flag = "🟢 проанализирован" if site_ok else "🟡 не удалось"

        # Hot/warm/cold классификация
        has_phone_or_tg = bool(
            getattr(report, "client_phone", None) or getattr(report, "client_telegram", None)
        )
        if has_phone_or_tg or score < 40:
            temperature = "🔥 HOT"
        elif score < 60:
            temperature = "🌡 WARM"
        else:
            temperature = "❄️ COLD"

        keyboard = [
            [
                {"text": "✉️ Отправить как есть", "callback_data": f"action:{report.id}:send_as_is"},
                {"text": "✍️ Добавить заметку", "callback_data": f"action:{report.id}:add_note"},
            ],
            [
                {"text": "🤐 Не отправлять", "callback_data": f"action:{report.id}:hold"},
            ],
        ]
        await self._send_with_keyboard(
            f"📊 <b>Отчёт готов #{str(report.id)[:8]}</b>\n\n"
            f"🏢 <b>{report.brand_name}</b> ({report.url})\n"
            f"{score_emoji} Score: {score}/100\n"
            f"📧 {report.email}\n"
            f"🎯 Top конкурент: {(report.competitors or ['—'])[0]}\n\n"
            f"<b>Quality flags:</b>\n"
            f"{cs_flag} — источник конкурентов\n"
            f"{site_flag} — анализ сайта\n"
            f"Признак лида: <b>{temperature}</b>\n\n"
            f"⏰ Авто-отправка через {settings.EXPERT_REVIEW_TIMEOUT_MINUTES} минут.\n"
            f"🔗 https://catcore.ru/otchet/{report.id}",
            keyboard=keyboard,
        )

    async def notify_hot_lead(self, report, contact: dict, eta_minutes: int = 5) -> None:
        """Этап 4.3.1 ТЗ — клиент оставил телефон/Telegram на странице ожидания.

        Отправляется НЕМЕДЛЕННО, не дожидаясь окончания pipeline. Эксперт получает
        контакты и должен связаться в течение 24 рабочих часов.

        Триггер этого метода — POST /api/v1/report/{id}/contact (появится в Этапе 5).
        """
        phone = contact.get("phone")
        tg = contact.get("telegram")
        name = contact.get("name") or "—"
        preferred = contact.get("preferred_time") or "любое"

        phone_line = f'📞 <a href="tel:{phone}">{phone}</a>' if phone else ""
        tg_line = f'✈️ <a href="https://t.me/{tg.lstrip("@")}">{tg}</a>' if tg else ""

        await self._send(
            f"🔥 <b>ГОРЯЧИЙ ЛИД</b>\n\n"
            f"🏢 <b>{report.brand_name}</b>\n"
            f'🌐 <a href="{report.url}">{report.url}</a>\n'
            f"🌍 {report.region}\n\n"
            f"<b>Контакт:</b>\n"
            f"👤 Имя: {name}\n"
            f"{phone_line}\n"
            f"{tg_line}\n"
            f"📧 Email: {report.email}\n"
            f"🕐 Удобное время: {preferred}\n\n"
            f"⚠️ Отчёт ещё генерируется (готовность через ~{eta_minutes} мин).\n"
            f"<b>Связаться с клиентом нужно в течение 24 рабочих часов.</b>"
        )

    async def notify_report_completed(self, report) -> None:
        score = report.visibility_score or 0
        score_emoji = "🔴" if score < 30 else "🟡" if score < 60 else "🟢"
        await self._send(
            f"📊 <b>Отчёт отправлен клиенту</b>\n\n"
            f"🏢 {report.brand_name}\n"
            f"{score_emoji} Score: {score}/100\n"
            f"📧 {report.email}\n\n"
            f"🔗 https://catcore.ru/otchet/{report.id}"
        )

    async def notify_cta_click(self, report, cta_data: dict) -> None:
        await self._send(
            f"🔥🔥🔥 <b>ГОРЯЧИЙ ЛИД — КЛИЕНТ ХОЧЕТ КОНСУЛЬТАЦИЮ</b>\n\n"
            f"🏢 {report.brand_name}\n"
            f"📊 Score: {report.visibility_score}/100\n"
            f"📧 {report.email}\n"
            f"💬 Telegram: {cta_data.get('telegram', 'не указан')}\n\n"
            f"📝 Комментарий: {cta_data.get('comment', '—')}\n\n"
            f"⚡ <b>Свяжитесь как можно скорее!</b>\n"
            f"🔗 https://catcore.ru/otchet/{report.id}"
        )

    async def notify_high_risk(self, report, reason: str) -> None:
        await self._send(
            f"🚨 <b>Подозрительная заявка</b>\n\n"
            f"📧 {report.email}\n"
            f"🏢 {report.brand_name}\n"
            f"⚠️ Причина: {reason}\n\n"
            f"Действие: rate-limit увеличен."
        )

    async def notify_pipeline_failed(self, report_id: UUID, error: str) -> None:
        await self._send(
            f"❌ <b>Ошибка генерации отчёта</b>\n\n"
            f"ID: {str(report_id)[:8]}\n"
            f"Ошибка: {error[:200]}"
        )
