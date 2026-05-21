"""Главный pipeline генерации отчёта. Запускается из Celery-таска."""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.analyzer import analyze_responses
from app.core.competitor_finder import find_competitors
from app.core.niche_detector import detect_niche
from app.core.prompt_generator import generate_prompts
from app.core.recommender import generate_recommendations
from app.core.scorer import (
    calculate_visibility_score,
    calculate_share_of_voice,
    calculate_presence_rate,
    compare_with_competitors,
)
from app.db.repositories.report_repo import get_report, update_report_status, update_report_field
from app.utils.logger import get_logger

logger = get_logger(__name__)

PROGRESS_MESSAGES = {
    "niche_detection": "Определяем нишу вашего бизнеса...",
    "competitor_discovery": "Подбираем ваших главных конкурентов...",
    "prompt_generation": "Генерируем 15 типичных запросов клиентов...",
    "polling_models": "Опрашиваем ИИ-ассистентов: ChatGPT, YandexGPT, Алиса, GigaChat, Gemini, DeepSeek...",
    "analyzing_responses": "Анализируем 90+ ответов ИИ-моделей...",
    "calculating_score": "Считаем AI Visibility Score...",
    "generating_recommendations": "Готовим персональные рекомендации...",
    "building_pdf": "Собираем PDF-отчёт...",
    "awaiting_personal_note": "Отчёт готов — ожидаем личную заметку эксперта...",
    "sending_email": "Отправляем отчёт на ваш email...",
    "completed": "Готово!",
}


def _build_pollers(cache, config) -> list:
    """Создаёт поллеры для включённых моделей."""
    from app.llm_pollers.openai_poller import OpenAIPoller
    from app.llm_pollers.yandex_poller import YandexGPTPoller
    from app.llm_pollers.alisa_poller import AlisaPoller
    from app.llm_pollers.gigachat_poller import GigaChatPoller
    from app.llm_pollers.gemini_poller import GeminiPoller
    from app.llm_pollers.deepseek_poller import DeepSeekPoller
    from app.llm_pollers.perplexity_poller import PerplexityPoller

    all_pollers = {
        "chatgpt": OpenAIPoller,
        "yandexgpt": YandexGPTPoller,
        "alisa": AlisaPoller,
        "gigachat": GigaChatPoller,
        "gemini": GeminiPoller,
        "deepseek": DeepSeekPoller,
        "perplexity": PerplexityPoller,
    }

    enabled = config.enabled_models_list
    return [
        cls(cache, config)
        for name, cls in all_pollers.items()
        if name in enabled
    ]


async def poll_all_models(
    prompts: list[str],
    pollers: list,
    niche_key: str,
) -> dict[str, dict[str, object]]:
    """Опрашивает все модели по всем промптам параллельно."""
    sem = asyncio.Semaphore(10)

    async def query_one(poller, prompt):
        async with sem:
            return await poller.query(prompt, niche_key)

    results: dict[str, dict] = {p.name: {} for p in pollers}
    tasks = [
        (poller.name, prompt, query_one(poller, prompt))
        for poller in pollers
        for prompt in prompts
    ]

    responses = await asyncio.gather(*[t[2] for t in tasks], return_exceptions=True)

    from app.llm_pollers.base import LLMResponse
    for (model_name, prompt, _), response in zip(tasks, responses):
        if isinstance(response, Exception):
            results[model_name][prompt] = LLMResponse(
                model_name=model_name,
                prompt=prompt,
                response_text="",
                error=str(response),
            )
        else:
            results[model_name][prompt] = response

    return results


async def generate_report(report_id: UUID, db: AsyncSession) -> None:
    """Главный pipeline. Запускается из Celery-таска после верификации email."""
    from app.cache.redis_cache import RedisCache
    from app.core.report_builder import build_and_upload_pdf
    from app.email.sender import EmailSender
    from app.integrations.telegram import TelegramNotifier
    from app.integrations.google_sheets import GoogleSheetsCRM

    redis_cache = RedisCache(settings.REDIS_URL)
    telegram = TelegramNotifier(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_NOTIFY_CHAT_ID)
    email_sender = EmailSender(settings)

    try:
        # ШАГ 1: Загрузка данных
        report = await get_report(db, report_id)
        if not report:
            logger.error("pipeline_report_not_found", report_id=str(report_id))
            return

        await update_report_status(db, report_id, "niche_detection", progress=5)

        # ШАГ 2: Ниша — учитываем подсказку клиента из формы (niche_data.user_hint).
        user_hint = None
        if isinstance(report.niche_data, dict):
            user_hint = report.niche_data.get("user_hint")
        niche = await detect_niche(report.url, report.brand_name, report.region, user_hint=user_hint)
        await update_report_field(db, report_id, niche_data=niche)
        await update_report_status(db, report_id, "competitor_discovery", progress=15)

        # ШАГ 3: Конкуренты (Этап 1.1 ТЗ — учитываем указанных клиентом).
        client_competitors = (
            list(report.client_competitors)
            if isinstance(report.client_competitors, list)
            else None
        )
        competitors, competitors_source = await find_competitors(
            niche,
            brand_name=report.brand_name,
            count=settings.COMPETITORS_PER_REPORT,
            client_competitors=client_competitors,
        )
        await update_report_field(
            db,
            report_id,
            competitors=competitors,
            competitors_source=competitors_source,
        )
        await update_report_status(db, report_id, "prompt_generation", progress=25)

        # ШАГ 4: Промпты
        prompts = await generate_prompts(niche, count=settings.PROMPTS_PER_REPORT)
        await update_report_field(db, report_id, prompts=prompts)
        await update_report_status(db, report_id, "polling_models", progress=35)

        # ШАГ 5: Опрос моделей
        pollers = _build_pollers(redis_cache, settings)
        niche_key = f"{niche.get('category', '')}:{report.region}"
        raw_responses = await poll_all_models(prompts, pollers, niche_key)

        # Сохраняем только тексты (JSONB не хранит объекты LLMResponse)
        raw_responses_json = {
            model: {prompt: r.response_text for prompt, r in prompt_map.items()}
            for model, prompt_map in raw_responses.items()
        }
        await update_report_field(db, report_id, raw_responses=raw_responses_json)
        await update_report_status(db, report_id, "analyzing_responses", progress=70)

        # ШАГ 6: Анализ
        all_brands = [report.brand_name] + (competitors or [])
        analysis = await analyze_responses(raw_responses, all_brands)
        await update_report_field(db, report_id, analysis=analysis.to_dict())
        await update_report_status(db, report_id, "calculating_score", progress=85)

        # ШАГ 7: Score
        score = calculate_visibility_score(analysis, report.brand_name)
        presence_rate = calculate_presence_rate(analysis, report.brand_name)
        sov = calculate_share_of_voice(analysis, report.brand_name)
        await update_report_field(
            db,
            report_id,
            visibility_score=score,
            presence_rate=presence_rate,
            share_of_voice=int(sov),
        )
        await update_report_status(db, report_id, "generating_recommendations", progress=92)

        # ШАГ 8: Рекомендации
        recommendations = await generate_recommendations(
            analysis, niche, report.brand_name, score, presence_rate, competitors or []
        )
        await update_report_field(db, report_id, recommendations=recommendations)
        await update_report_status(db, report_id, "building_pdf", progress=96)

        # ШАГ 9: PDF
        report_fresh = await get_report(db, report_id)
        pdf_url = await build_and_upload_pdf(report_fresh, analysis, competitors or [])
        await update_report_field(db, report_id, pdf_url=pdf_url)

        # ШАГ 10: Workflow эксперта или авто-отправка
        if settings.EXPERT_REVIEW_BEFORE_SEND:
            await update_report_status(db, report_id, "awaiting_personal_note", progress=99)
            try:
                await telegram.notify_report_ready_for_review(report_fresh, score)
            except Exception as tg_exc:
                logger.error("telegram_notify_expert_failed", error=repr(tg_exc), error_type=type(tg_exc).__name__)
            # Авто-отправка запустится через Celery beat-таск после таймаута
            from app.tasks.generate_report import auto_send_report_after_timeout
            auto_send_report_after_timeout.apply_async(
                args=[str(report_id)],
                countdown=settings.EXPERT_REVIEW_TIMEOUT_MINUTES * 60,
            )
        else:
            await update_report_status(db, report_id, "sending_email", progress=99)
            report_final = await get_report(db, report_id)
            await email_sender.send_report_ready(report_final)
            await update_report_status(db, report_id, "completed", progress=100)
            await telegram.notify_report_completed(report_final)

        # Google Sheets
        try:
            crm = GoogleSheetsCRM(
                settings.GOOGLE_SHEETS_CREDENTIALS_PATH,
                settings.GOOGLE_SHEETS_SPREADSHEET_ID,
            )
            report_final = await get_report(db, report_id)
            await crm.add_lead(report_final, "report_completed")
        except Exception as exc:
            logger.error("google_sheets_error", error=str(exc))

        logger.info("pipeline_completed", report_id=str(report_id), score=score)

    except Exception as exc:
        logger.error("pipeline_failed", report_id=str(report_id), error=str(exc))
        await update_report_status(
            db, report_id, "failed", progress=0, error_message=str(exc)
        )
        try:
            await telegram.notify_pipeline_failed(report_id, str(exc))
        except Exception:
            pass
        raise
