from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader

from app.utils.logger import get_logger

logger = get_logger(__name__)


class EmailSender:
    def __init__(self, config):
        self.smtp_host = config.SMTP_HOST
        self.smtp_port = config.SMTP_PORT
        self.smtp_user = config.SMTP_USER
        self.smtp_password = config.SMTP_PASSWORD
        self.from_email = config.FROM_EMAIL
        self.from_name = config.STUDIO_NAME
        self.config = config

        templates_dir = Path(__file__).parent / "templates"
        self.template_env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True,
        )

    def _base_context(self) -> dict:
        return {
            "EXPERT_NAME": self.config.EXPERT_NAME,
            "EXPERT_TITLE": self.config.EXPERT_TITLE,
            "EXPERT_PHOTO_URL": self.config.EXPERT_PHOTO_URL,
            "STUDIO_NAME": self.config.STUDIO_NAME,
            "STUDIO_FULL_URL": self.config.STUDIO_FULL_URL,
            "CONTACT_TG_BOT_URL": self.config.CONTACT_TG_BOT_URL,
            "CONTACT_TG_BOT": self.config.CONTACT_TG_BOT,
        }

    async def send(
        self,
        to_email: str,
        subject: str,
        template_name: str,
        context: dict,
    ) -> bool:
        try:
            full_context = {**self._base_context(), **context}
            template = self.template_env.get_template(template_name)
            html_content = template.render(**full_context)

            message = EmailMessage()
            message["From"] = f"{self.from_name} <{self.from_email}>"
            message["To"] = to_email
            message["Subject"] = subject
            message.set_content("Это письмо требует HTML-просмотра.")
            message.add_alternative(html_content, subtype="html")

            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                use_tls=(self.smtp_port == 465),
                start_tls=(self.smtp_port == 587),
            )
            logger.info("email_sent", to=to_email, template=template_name)
            return True
        except Exception as exc:
            logger.error("email_send_failed", to=to_email, error=str(exc))
            return False

    async def send_verification(self, report) -> bool:
        verification_url = f"{self.config.STUDIO_FULL_URL}/api/v1/verify/{report.email_verification_token}"
        return await self.send(
            to_email=report.email,
            subject=f"Подтвердите запрос проверки видимости {report.brand_name}",
            template_name="verify.html",
            context={
                "brand_name": report.brand_name,
                "verification_url": verification_url,
            },
        )

    async def send_report_ready(self, report) -> bool:
        report_url = f"{self.config.STUDIO_FULL_URL}/otchet/{report.id}"
        return await self.send(
            to_email=report.email,
            subject=f"AI Visibility Score {report.brand_name}: {report.visibility_score}/100",
            template_name="report_ready.html",
            context={
                "brand_name": report.brand_name,
                "score": report.visibility_score,
                "report_url": report_url,
                "pdf_url": report.pdf_url,
                "expert_note": report.expert_note,
            },
        )

    async def send_followup(self, report, day: int) -> bool:
        template_map = {
            2: "followup_day_2.html",
            7: "followup_day_7.html",
        }
        template = template_map.get(day)
        if not template:
            return False

        competitors = report.competitors or []
        top_competitor = competitors[0] if competitors else "конкурент"

        return await self.send(
            to_email=report.email,
            subject=(
                f"Почему {top_competitor} обгоняет вас в ChatGPT"
                if day == 2
                else f"За 90 дней с {report.visibility_score} до {report.visibility_score + 25} — конкретный план"
            ),
            template_name=template,
            context={
                "brand_name": report.brand_name,
                "score": report.visibility_score,
                "top_competitor": top_competitor,
                "report_url": f"{self.config.STUDIO_FULL_URL}/otchet/{report.id}",
            },
        )
