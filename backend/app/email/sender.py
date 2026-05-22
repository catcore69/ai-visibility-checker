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
        base = self.config.STUDIO_FULL_URL.rstrip("/")
        report_url = f"{base}/otchet/{report.id}"
        # Скачивание PDF идёт через НАШ домен (а не через прямую ссылку на S3) —
        # иначе Avast/Касперский флагят `s3.twcstorage.ru` как фишинг.
        pdf_url = f"{base}/api/v1/report/{report.id}/pdf/file"
        booking_url = (
            f"{base}/zapis-na-razgovor?report_id={report.id}"
            f"&utm_source=ai_report&utm_campaign=cta_call_email_report_ready"
        )
        unsubscribe_url = (
            f"{base}/api/v1/report/{report.id}/unsubscribe"
            f"?token={getattr(report, 'unsubscribe_token', '') or ''}"
        )

        # Подсчёт упоминаний для блока 3 ключевых цифр
        your_mentions = None
        total_prompts = None
        try:
            total_prompts = len(report.prompts or [])
            if report.presence_rate and total_prompts:
                your_mentions = int(round(report.presence_rate * total_prompts / 100))
        except Exception:
            pass

        # Главный конкурент — из competitors list (порядок = сила)
        top_competitor = None
        top_competitor_score = None
        comps = report.competitors or []
        if comps:
            top_competitor = comps[0]
            # Score конкурента в Этапе 3 ТЗ берётся из competitor_comparison,
            # но в Report у нас не лежит — оставим None, шаблон корректно покажет
            # только имя.

        return await self.send(
            to_email=report.email,
            subject=f"{report.brand_name}: ваш AI Visibility Score — {report.visibility_score}/100",
            template_name="report_ready.html",
            context={
                "brand_name": report.brand_name,
                "score": report.visibility_score,
                "report_url": report_url,
                "pdf_url": pdf_url,
                "booking_url": booking_url,
                "unsubscribe_url": unsubscribe_url,
                "expert_note": report.expert_note,
                "your_mentions": your_mentions,
                "total_prompts": total_prompts,
                "top_competitor": top_competitor,
                "top_competitor_score": top_competitor_score,
                "key_insight": self._build_key_insight(report),
            },
        )

    def _build_key_insight(self, report) -> str:
        """Главный инсайт одной строкой — для письма и follow-up.

        Берём из gap_analysis (Этап 2) либо из top_weakness, либо генерируем
        фразу по Score.
        """
        gap = report.gap_analysis or {}
        key_gaps = gap.get("key_gaps") if isinstance(gap, dict) else None
        if key_gaps and isinstance(key_gaps, list) and len(key_gaps) > 0:
            first = key_gaps[0]
            title = first.get("title") if isinstance(first, dict) else None
            if title:
                return f"главный технический разрыв с лидером ниши — «{title}»."

        score = report.visibility_score or 0
        if score < 30:
            return "ваш бренд почти невидим для ИИ — это критично, но исправимо."
        if score < 60:
            return "ИИ-ассистенты вас знают, но рекомендуют других. Есть конкретные точки роста."
        return "вы в игре. Главное — удержать позиции и закрепиться в топе."

    async def send_followup_v2(self, report, followup_type: str) -> bool:
        """Отправка одного follow-up письма (Этап 4.2 ТЗ).

        followup_type: "day_3" / "day_10" / "day_30".
        """
        base = self.config.STUDIO_FULL_URL.rstrip("/")
        report_url = f"{base}/otchet/{report.id}"
        booking_url = (
            f"{base}/zapis-na-razgovor?report_id={report.id}"
            f"&utm_source=ai_report&utm_campaign=cta_call_followup_{followup_type}"
        )
        unsubscribe_url = (
            f"{base}/api/v1/report/{report.id}/unsubscribe"
            f"?token={getattr(report, 'unsubscribe_token', '') or ''}"
        )
        recheck_url = (
            f"{base}/proverka?url={report.url}&prefill=1"
            f"&utm_source=ai_report&utm_campaign=cta_recheck_day_30"
        )

        templates = {
            "day_3": "followup_day_3.html",
            "day_10": "followup_day_10.html",
            "day_30": "followup_day_30.html",
        }
        subjects = {
            "day_3": f"{report.brand_name}: видели наш отчёт?",
            "day_10": f"{report.brand_name}: 1 идея, что можно сделать на этой неделе",
            "day_30": f"{report.brand_name}: через месяц перепроверим?",
        }
        if followup_type not in templates:
            logger.error("send_followup_v2_unknown_type", type=followup_type)
            return False

        # Для day_10 — конкретная идея из level-1 рекомендаций
        idea = None
        if followup_type == "day_10":
            recs = report.recommendations or []
            for r in recs:
                if isinstance(r, dict) and r.get("effort") == "low":
                    idea = r.get("description") or r.get("title")
                    if idea:
                        break

        return await self.send(
            to_email=report.email,
            subject=subjects[followup_type],
            template_name=templates[followup_type],
            context={
                "brand_name": report.brand_name,
                "score": report.visibility_score,
                "report_url": report_url,
                "booking_url": booking_url,
                "unsubscribe_url": unsubscribe_url,
                "recheck_url": recheck_url,
                "key_insight": self._build_key_insight(report),
                "idea": idea,
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
