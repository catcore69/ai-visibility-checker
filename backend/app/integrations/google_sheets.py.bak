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
                report.visibility_score or "",
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
