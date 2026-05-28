"""Интеграция с Bitrix24 CRM (Этап 4.4 ТЗ).

Воронка «AI Visibility Reports» в дефолтной категории (CATEGORY_ID=0).
Коды кастомных полей совпадают с ТЗ (UF_CRM_*), коды стадий — STATUS_ID
из настройки фаундера. Важно: «Не наша ниша» = системная стадия LOSE.

Клиент работает через входящий вебхук Bitrix24 (REST API):
  https://catcore.bitrix24.by/rest/{user_id}/{webhook_key}/{method}.json

Если BITRIX24_ENABLED=false или нет webhook URL — все методы no-op,
pipeline продолжает работать без CRM.
"""

from typing import Any, Optional

import httpx

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ===== Стадии воронки (STATUS_ID в Bitrix) =====
STAGE_NEW = "NEW"
STAGE_CONTACT_GIVEN = "CONTACT_GIVEN"
STAGE_CALL_SCHEDULED = "CALL_SCHEDULED"
STAGE_CALL_DONE = "CALL_DONE"
STAGE_KP_SENT = "KP_SENT"
STAGE_WON = "WON"
# Внимание: «Не наша ниша» — системная стадия Bitrix, её ID нельзя поменять.
STAGE_LOST_NOT_FIT = "LOSE"
STAGE_LOST_NOT_READY = "LOST_NOT_READY"
STAGE_LOST_EXPENSIVE = "LOST_EXPENSIVE"
STAGE_LOST_COMPETITOR = "LOST_COMPETITOR"
STAGE_LOST_NO_RESPONSE = "LOST_NO_RESPONSE"

# ===== Коды кастомных полей сделки (совпадают с ТЗ) =====
F_REPORT_ID = "UF_CRM_REPORT_ID"
F_URL = "UF_CRM_URL"
F_NICHE = "UF_CRM_NICHE"
F_REGION = "UF_CRM_REGION"
F_SCORE = "UF_CRM_SCORE"
F_TOP_COMPETITOR = "UF_CRM_TOP_COMPETITOR"
F_TOP_GAP = "UF_CRM_TOP_GAP"
F_REPORT_PDF_URL = "UF_CRM_REPORT_PDF_URL"
F_COMPETITORS_SOURCE = "UF_CRM_COMPETITORS_SOURCE"
F_HOT_LEAD_SCORE = "UF_CRM_HOT_LEAD_SCORE"
F_KP_REQUESTED = "UF_CRM_KP_REQUESTED"
F_CALL_OUTCOME = "UF_CRM_CALL_OUTCOME"
F_NEXT_STEP = "UF_CRM_NEXT_STEP_AFTER_CALL"
F_EXPERT_NOTES = "UF_CRM_EXPERT_NOTES"


def compute_hot_lead_score(report, has_contact: bool = False) -> str:
    """Классификация горячести лида (ТЗ 4.3.2): hot / warm / cold.

    - hot  — оставлен телефон/Telegram ИЛИ Score < 40
    - warm — Score 40–60
    - cold — остальное
    """
    score = report.visibility_score or 0
    if has_contact or score < 40:
        return "hot"
    if score <= 60:
        return "warm"
    return "cold"


def _top_gap_text(report) -> str:
    """Короткое описание ключевого разрыва из gap_analysis для поля сделки."""
    gap = getattr(report, "gap_analysis", None) or {}
    key_gaps = gap.get("key_gaps") if isinstance(gap, dict) else None
    if key_gaps and isinstance(key_gaps, list):
        titles = [g.get("title") for g in key_gaps if isinstance(g, dict) and g.get("title")]
        if titles:
            return "; ".join(titles[:3])
    return ""


class Bitrix24Client:
    """Тонкий клиент над REST API Bitrix24 через входящий вебхук."""

    def __init__(self):
        self.enabled = bool(settings.BITRIX24_ENABLED and settings.BITRIX24_WEBHOOK_URL)
        self.base = (settings.BITRIX24_WEBHOOK_URL or "").rstrip("/")
        self.category_id = settings.BITRIX24_CATEGORY_ID or "0"

    async def _call(self, method: str, params: dict) -> Optional[dict]:
        """Вызов REST-метода. Возвращает result или None при ошибке/выключенности."""
        if not self.enabled:
            return None
        url = f"{self.base}/{method}.json"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=params)
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    logger.error(
                        "bitrix24_api_error",
                        method=method,
                        error=data.get("error"),
                        desc=data.get("error_description"),
                    )
                    return None
                return data.get("result")
        except Exception as exc:
            logger.error("bitrix24_call_failed", method=method, error=str(exc))
            return None

    async def find_deal_by_report_id(self, report_id: str) -> Optional[str]:
        """Ищет существующую сделку по UF_CRM_REPORT_ID. Возвращает deal_id или None."""
        result = await self._call(
            "crm.deal.list",
            {
                "filter": {F_REPORT_ID: str(report_id)},
                "select": ["ID"],
            },
        )
        if result and isinstance(result, list) and len(result) > 0:
            return str(result[0].get("ID"))
        return None

    def _build_fields(self, report, stage: str, contact: Optional[dict] = None) -> dict:
        """Собирает поля сделки из отчёта."""
        comps = report.competitors or []
        has_contact = bool(contact and (contact.get("phone") or contact.get("telegram")))
        fields: dict[str, Any] = {
            "TITLE": f"AI Visibility: {report.brand_name}",
            "CATEGORY_ID": self.category_id,
            "STAGE_ID": stage,
            F_REPORT_ID: str(report.id),
            F_URL: report.url or "",
            F_NICHE: (report.niche_data or {}).get("category", "") if isinstance(report.niche_data, dict) else "",
            F_REGION: report.region or "",
            F_COMPETITORS_SOURCE: getattr(report, "competitors_source", None) or "llm",
            F_HOT_LEAD_SCORE: compute_hot_lead_score(report, has_contact),
        }
        # Поля, появляющиеся только после готовности отчёта
        if report.visibility_score is not None:
            fields[F_SCORE] = report.visibility_score
        if comps:
            fields[F_TOP_COMPETITOR] = comps[0]
        gap_text = _top_gap_text(report)
        if gap_text:
            fields[F_TOP_GAP] = gap_text
        if getattr(report, "pdf_url", None):
            # PDF лучше отдавать через наш домен (не S3 — антивирусы блокируют)
            base = settings.STUDIO_FULL_URL.rstrip("/")
            fields[F_REPORT_PDF_URL] = f"{base}/api/v1/report/{report.id}/pdf/file"

        # Контактные данные (стадия CONTACT_GIVEN)
        if contact:
            if contact.get("name"):
                fields["NAME"] = contact["name"]
            if contact.get("phone"):
                fields["PHONE"] = [{"VALUE": contact["phone"], "VALUE_TYPE": "WORK"}]
            if report.email:
                fields["EMAIL"] = [{"VALUE": report.email, "VALUE_TYPE": "WORK"}]
            # Telegram кладём в комментарий — у сделки нет штатного поля мессенджера
            if contact.get("telegram"):
                fields["COMMENTS"] = f"Telegram: {contact['telegram']}"
        elif report.email:
            fields["EMAIL"] = [{"VALUE": report.email, "VALUE_TYPE": "WORK"}]

        return fields

    async def create_deal(
        self, report, stage: str = STAGE_NEW, contact: Optional[dict] = None
    ) -> Optional[str]:
        """Создаёт сделку. Возвращает deal_id."""
        fields = self._build_fields(report, stage, contact)
        result = await self._call("crm.deal.add", {"fields": fields})
        if result:
            deal_id = str(result)
            logger.info("bitrix24_deal_created", deal_id=deal_id, report_id=str(report.id), stage=stage)
            return deal_id
        return None

    async def update_deal(self, deal_id: str, fields: dict) -> bool:
        result = await self._call("crm.deal.update", {"id": deal_id, "fields": fields})
        return result is not None

    async def update_deal_stage(self, deal_id: str, stage: str) -> bool:
        return await self.update_deal(deal_id, {"STAGE_ID": stage})

    async def upsert_deal(
        self, report, stage: str = STAGE_NEW, contact: Optional[dict] = None
    ) -> Optional[str]:
        """Идемпотентно: если сделка по report_id есть — обновляет, иначе создаёт.

        Логика стадий (ТЗ 4.4.2):
        - Существующую сделку НЕ откатываем назад по воронке. Если она уже,
          например, в CALL_SCHEDULED, и приходит апдейт со стадией NEW —
          стадию не трогаем, только обновляем поля.
        """
        if not self.enabled:
            return None

        existing_id = await self.find_deal_by_report_id(str(report.id))
        fields = self._build_fields(report, stage, contact)

        if existing_id:
            # Не понижаем стадию: убираем STAGE_ID из апдейта, если сделка уже продвинута.
            # Простая защита — обновляем стадию только если явно CONTACT_GIVEN
            # (горячий лид важнее, чем NEW).
            if stage == STAGE_NEW:
                fields.pop("STAGE_ID", None)
            await self.update_deal(existing_id, fields)
            logger.info("bitrix24_deal_updated", deal_id=existing_id, report_id=str(report.id))
            return existing_id

        return await self.create_deal(report, stage, contact)
