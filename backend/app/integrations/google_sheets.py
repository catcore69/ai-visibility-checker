import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class GoogleSheetsCRM:
    def __init__(self, credentials_path: str, spreadsheet_id: str):
        self.credentials_path = credentials_path
        self.spreadsheet_id = spreadsheet_id
        self._sheet = None

    def _get_sheet(self):
        if self._sheet is not None:
            return self._sheet

        if not Path(self.credentials_path).exists():
            raise FileNotFoundError(f"Google credentials not found: {self.credentials_path}")

        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self.spreadsheet_id)
        self._sheet = spreadsheet.worksheet("Лиды")
        return self._sheet

    async def add_lead(self, report, event: str, extra: Optional[dict] = None) -> None:
        """Добавляет строку в Google Sheets журнал лидов."""
        try:
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                report.email,
                report.url,
                report.brand_name,
                report.region,
                (report.visibility_score if report.visibility_score is not None else ""),
                report.status,
                event,
                report.utm_source or "",
                report.utm_medium or "",
                report.utm_campaign or "",
                "",  # Заметки — вручную
                "",  # Дата контакта — вручную
                "",  # Результат — вручную
            ]
            sheet = await asyncio.to_thread(self._get_sheet)
            await asyncio.to_thread(sheet.append_row, row)
        except Exception as exc:
            logger.error("google_sheets_error", error=str(exc))
            # Не падаем — основной процесс важнее

    def _get_crm_sheet(self):
        """Лист-зеркало Bitrix24 (Этап 4.5 ТЗ). Отдельный от 'Лиды'."""
        if getattr(self, "_crm_sheet", None) is not None:
            return self._crm_sheet

        from pathlib import Path
        if not Path(self.credentials_path).exists():
            raise FileNotFoundError(f"Google credentials not found: {self.credentials_path}")

        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(self.spreadsheet_id)
        # Лист "CRM" — зеркало сделок Bitrix24. Создаём, если нет.
        try:
            self._crm_sheet = spreadsheet.worksheet("CRM")
        except Exception:
            self._crm_sheet = spreadsheet.add_worksheet(title="CRM", rows=1000, cols=20)
            self._crm_sheet.append_row(_CRM_HEADER)
        return self._crm_sheet

    async def upsert_deal_row(self, deal_fields: dict) -> None:
        """Зеркалирует сделку Bitrix24 в лист CRM (Этап 4.5 ТЗ).

        Синхронизация ОДНОСТОРОННЯЯ: Bitrix24 → Sheets. Ключ строки — report_id.
        Если строка с таким report_id есть — обновляем, иначе добавляем.

        deal_fields — нормализованный dict из webhook-приёмника.
        """
        try:
            report_id = str(deal_fields.get("report_id", "")).strip()
            if not report_id:
                return

            row = [
                deal_fields.get("report_id", ""),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                deal_fields.get("stage", ""),
                deal_fields.get("brand_name", ""),
                deal_fields.get("url", ""),
                deal_fields.get("niche", ""),
                deal_fields.get("region", ""),
                deal_fields.get("score", ""),
                deal_fields.get("top_competitor", ""),
                deal_fields.get("competitors_source", ""),
                deal_fields.get("hot_lead_score", ""),
                deal_fields.get("email", ""),
                deal_fields.get("phone", ""),
                deal_fields.get("call_outcome", ""),
                deal_fields.get("deal_id", ""),
            ]

            sheet = await asyncio.to_thread(self._get_crm_sheet)

            # Ищем строку по report_id (колонка A)
            try:
                cell = await asyncio.to_thread(sheet.find, report_id, None, 1)
            except Exception:
                cell = None

            if cell:
                # Обновляем существующую строку
                await asyncio.to_thread(
                    sheet.update,
                    f"A{cell.row}:O{cell.row}",
                    [row],
                )
                logger.info("sheets_crm_updated", report_id=report_id, row=cell.row)
            else:
                await asyncio.to_thread(sheet.append_row, row)
                logger.info("sheets_crm_appended", report_id=report_id)
        except Exception as exc:
            logger.error("sheets_crm_upsert_error", error=str(exc))


# Заголовок листа CRM — повторяет ключевые поля сделки Bitrix24.
_CRM_HEADER = [
    "report_id",
    "updated_at",
    "stage",
    "brand_name",
    "url",
    "niche",
    "region",
    "score",
    "top_competitor",
    "competitors_source",
    "hot_lead_score",
    "email",
    "phone",
    "call_outcome",
    "deal_id",
]
