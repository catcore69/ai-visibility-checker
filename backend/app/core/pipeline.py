"""Главный pipeline генерации отчёта. Запускается из Celery-таска."""

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.analyzer import analyze_responses
from app.core.competitor_finder import build_competitor_list, find_competitor_url
from app.core.gap_analyzer import build_gap_analysis
from app.core.niche_detector import detect_niche
from app.core.prompt_generator import generate_prompts
from app.core.recommender import generate_recommendations
from app.core.site_analyzer import analyze_site
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
    "site_analysis": "Анализируем структуру вашего сайта и сайтов конкурентов...",
    "prompt_generation": "Генерируем 10 типичных запросов клиентов...",
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
    from app.llm_pollers.yandex_ai_search_poller import YandexAISearchPoller
    from app.llm_pollers.google_ai_overview_poller import GoogleAIOverviewPoller
    from app.llm_pollers.gigachat_poller import GigaChatPoller
    from app.llm_pollers.gemini_poller import GeminiPoller
    from app.llm_pollers.deepseek_poller import DeepSeekPoller
    from app.llm_pollers.perplexity_poller import PerplexityPoller

    all_pollers = {
        "chatgpt": OpenAIPoller,
        "yandexgpt": YandexGPTPoller,
        # Этап 2.4 ТЗ: "alisa" → "yandex_ai_search" (это XMLRiver SERP с AI-блоком,
        # не голосовой ассистент). Старый ключ "alisa" остаётся в БД мигрированным.
        "yandex_ai_search": YandexAISearchPoller,
        # Симметрично yandex_ai_search: AI-блок в выдаче Google (НЕ Gemini-модель).
        "google_ai_overview": GoogleAIOverviewPoller,
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
    region: str = "",
) -> dict[str, dict[str, object]]:
    """Опрашивает все модели по всем промптам параллельно.

    region — регион клиента; нужен поллерам с гео-привязкой
    (yandex_ai_search, google_ai_overview). Остальные игнорируют."""
    sem = asyncio.Semaphore(10)

    async def query_one(poller, prompt):
        async with sem:
            return await poller.query(prompt, niche_key, region=region)

    results: dict[str, dict] = {p.name: {} for p in pollers}
    tasks = [
        (poller.name, prompt, query_one(poller, prompt))
        for poller in pollers
        for prompt in prompts
    ]

    from app.llm_pollers.base import LLMResponse

    # ОБЩИЙ таймаут на весь опрос — вторая страховка от зомби-зависания
    # (если один поллер всё же блокирует надолго, отчёт не висит вечно).
    # Бюджет = LLM_CALL_TIMEOUT × число попыток × запас. Что не успело —
    # заполняется заглушкой, pipeline продолжается.
    overall_timeout = max(
        180, getattr(settings, "LLM_CALL_TIMEOUT", 45) * 4
    )
    try:
        responses = await asyncio.wait_for(
            asyncio.gather(*[t[2] for t in tasks], return_exceptions=True),
            timeout=overall_timeout,
        )
    except asyncio.TimeoutError:
        logger.error("poll_all_models_overall_timeout", timeout=overall_timeout)
        responses = [TimeoutError("overall poll timeout")] * len(tasks)

    for (model_name, prompt, _), response in zip(tasks, responses):
        if isinstance(response, BaseException):
            results[model_name][prompt] = LLMResponse(
                model_name=model_name,
                prompt=prompt,
                response_text="",
                error=str(response) or "poll error",
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

        # ===== Итерация-2, Б1: воспроизводимость =====
        # Если за NICHE_REUSE_DAYS уже был завершённый отчёт по этому домену —
        # берём из него нишу, регион и конкурентов. Тогда повторный анализ даёт
        # ТЕ ЖЕ нишу/запросы/конкурентов (запросы — из кеша по niche_key), а
        # меняются только свежие ответы моделей (это и есть «динамика»).
        from datetime import datetime, timedelta
        from app.db.repositories.report_repo import find_reusable_report_by_domain
        reused = None
        try:
            reuse_since = datetime.utcnow() - timedelta(days=settings.NICHE_REUSE_DAYS)
            reused = await find_reusable_report_by_domain(
                db, report.domain_normalized, reuse_since, exclude_id=report_id
            )
        except Exception as exc:
            logger.warning("niche_reuse_lookup_failed", error=str(exc))

        if reused and isinstance(reused.niche_data, dict) and reused.competitors:
            niche = dict(reused.niche_data)
            # ТЗ catcore-nisha-primary-secondary: гарантируем primary_* поля
            # для старых reuse-отчётов (back-compat). Если их нет — выводим
            # из старого subcategory.split(",").
            from app.core.niche_detector import normalize_niche as _norm
            niche = _norm(niche)
            effective_brand = reused.brand_name or report.brand_name
            effective_region = niche.get("region") or report.region or ""
            competitors = list(reused.competitors)
            competitors_source = reused.competitors_source or "reused"
            await update_report_field(
                db, report_id,
                niche_data=niche,
                brand_name=effective_brand,
                region=niche.get("region") or report.region,
                competitors=competitors,
                competitors_source=competitors_source,
            )
            report = await get_report(db, report_id)
            logger.info(
                "niche_competitors_reused",
                domain=report.domain_normalized,
                source_report=str(reused.id),
                competitors=len(competitors),
            )
            await update_report_status(db, report_id, "competitor_discovery", progress=15)
        else:
            # ШАГ 2а (Задача 4): РЕГИОН из жёстких сигналов сайта, а не из формы.
            # Форма больше не диктует регион (там был дефолт «Россия» — корень багов).
            from app.core.region_detector import detect_region
            region_info, site_text = await detect_region(report.url)
            detected_region = region_info.get("region") or ""  # "" если unknown
            # Если детектор уверенно определил регион — используем его как основной.
            effective_region = detected_region or report.region or ""

            # ШАГ 2б: Ниша — по РЕАЛЬНОМУ контенту сайта + определённому региону.
            user_hint = None
            if isinstance(report.niche_data, dict):
                user_hint = report.niche_data.get("user_hint")
            niche = await detect_niche(
                report.url,
                report.brand_name,
                effective_region,
                user_hint=user_hint,
                site_text=site_text,
            )
            # Кладём в niche итоговый регион + сигналы (для прозрачности/отладки).
            niche["region_detection"] = {
                "country": region_info.get("country"),
                "city": region_info.get("city"),
                "confidence": region_info.get("confidence"),
            }
            # Финальный регион. Если region_detector НЕ уверен (confidence != high)
            # и LLM region_uncertain → НЕ подставляем ничего случайного.
            # Метка region_uncertain попадает в niche, по ней дальше можно
            # пометить отчёт «регион требует уточнения».
            llm_region = (niche.get("region") or "").strip()
            llm_region_known = llm_region and llm_region.lower() != "unknown"
            detector_country = (region_info.get("country") or "").lower()
            detector_confident = (
                detector_country
                and detector_country != "unknown"
                and region_info.get("confidence") in ("high", "medium")
            )
            if detector_confident:
                final_region = effective_region
                region_uncertain = False
            elif llm_region_known:
                # LLM что-то сказала, но region_detector не подтвердил —
                # доверяем с пометкой «уверенности нет».
                final_region = llm_region
                region_uncertain = True
            else:
                final_region = ""  # без выдуманного дефолта
                region_uncertain = True
            niche["region"] = final_region
            niche["region_uncertain"] = region_uncertain
            if region_uncertain:
                logger.warning(
                    "region_uncertain",
                    brand=report.brand_name,
                    detector_country=region_info.get("country"),
                    detector_confidence=region_info.get("confidence"),
                    llm_region=llm_region,
                    final=final_region,
                )

            # Задача 5.1: бренд определён парсингом — обновляем имя бренда отчёта,
            # если форма прислала только URL-плейсхолдер.
            detected_brand = (niche.get("brand") or "").strip()
            effective_brand = detected_brand or report.brand_name
            await update_report_field(
                db, report_id,
                niche_data=niche,
                brand_name=effective_brand,
                region=final_region or report.region or "",
            )
            # Освежаем объект, чтобы дальше использовать новый бренд.
            report = await get_report(db, report_id)
            # Конкуренты определяем ПОСЛЕ опроса моделей (Итерация-3, Фаза 2) —
            # из реально упомянутых в ответах ИИ брендов. Пока не заданы.
            competitors = None
            competitors_source = None

        # ===== ШАГ 4: Промпты =====
        await update_report_status(db, report_id, "prompt_generation", progress=25)
        # Стоп-лист брендов из карточек бизнеса (только LOCAL): имена соседних
        # заведений-конкурентов, чтобы навигационные запросы вроде «база отдыха
        # белое озеро» не попали в опрос (разбор 800b4eca). Карточки — точный
        # источник этих имён собственных.
        query_exclude_names: list[str] = []
        try:
            from app.core.niche_detector import business_scope as _bscope
            if _bscope(niche) == "local":
                from app.core.competitor_finder import fetch_card_competitor_names
                query_exclude_names = await fetch_card_competitor_names(
                    niche, brand_name=report.brand_name
                )
                logger.info("query_stoplist_built", count=len(query_exclude_names))
        except Exception as exc:
            logger.warning("query_stoplist_failed", error=str(exc))
        prompts = await generate_prompts(
            niche, count=settings.PROMPTS_PER_REPORT,
            exclude_names=query_exclude_names,
        )
        await update_report_field(db, report_id, prompts=prompts)

        # ===== ШАГ 5: ПАРАЛЛЕЛЬНО — Блок А (SERP-конкуренты) И опрос моделей =====
        # По MD2 Часть 1: конкуренты из выдачи не зависят от ответов ИИ, гоним
        # одновременно с опросом. Это экономит ~минуту (опрос ≈45с/вызов × 7 моделей).
        await update_report_status(db, report_id, "polling_models", progress=35)
        pollers = _build_pollers(redis_cache, settings)
        niche_key = f"{niche.get('category', '')}:{report.region}"

        client_competitors = (
            list(report.client_competitors)
            if isinstance(report.client_competitors, list)
            else None
        )

        # Задача 1 ТЗ catcore-konkurenty-iz-ai-vydachi: Блок А теперь строится
        # КАСКАДОМ из AI-выдачи. Это требует raw_responses, поэтому Block A
        # ЖДЁТ опрос. Раньше шла параллельность Блок А + опрос — но AI-выдача
        # давала более качественных конкурентов, чем органический SERP
        # (см. кейс akbtrade.by, где SERP вернул телеком и недвижку как
        # «конкурентов» магазина АКБ). Параллельность убрана.
        if not (reused and competitors):
            raw_responses = await poll_all_models(
                prompts, pollers, niche_key, region=report.region
            )

            # ТЗ catcore-blok-a-iz-realnoy-vydachi: Блок А строится из
            # citations Google AI Overview <item> + органики SERP. НЕ из
            # LLM-извлечения по текстам моделей (это галлюцинирующий
            # источник — слоганы и агрегаторы прорывались в Блок А).
            ai_citations: dict[str, list[str]] = {}
            for poller in pollers:
                if hasattr(poller, "consume_citations"):
                    cits = poller.consume_citations() or {}
                    if cits:
                        ai_citations[poller.name] = cits
            try:
                competitors, competitors_source, competitor_sources_map = await build_competitor_list(
                    niche,
                    brand_name=report.brand_name,
                    client_competitors=client_competitors,
                    count=settings.COMPETITORS_PER_REPORT,
                    ai_citations=ai_citations,  # реальные URL из <item> AI Overview (LOCAL)
                    client_url=report.url or "",  # чтобы не попасть самим в Block A
                    raw_responses=raw_responses,  # для ONLINE_FEDERAL/PERSONAL_BRAND веток
                )
                logger.info(
                    "block_a_built",
                    competitors=competitors,
                    source=competitors_source,
                )
                await update_report_field(
                    db, report_id,
                    competitors=competitors,
                    competitors_source=competitors_source,
                )
            except Exception as exc:
                logger.error("block_a_failed", error=str(exc))
                competitors, competitors_source, competitor_sources_map = [], "sparse", {}
        else:
            raw_responses = await poll_all_models(prompts, pollers, niche_key, region=report.region)
            competitor_sources_map = (niche or {}).get("competitor_sources") or {}

        raw_responses_json = {
            model: {prompt: r.response_text for prompt, r in prompt_map.items()}
            for model, prompt_map in raw_responses.items()
        }
        await update_report_field(db, report_id, raw_responses=raw_responses_json)

        # ===== ШАГ 5.5: Блок Б — кого ИИ называет В НИШЕ (после опроса) =====
        # MD2 Часть 2: отдельный список «кого ИИ из вашей ниши уже знает»
        # (1С, Контур и т.п. для регионального B2B). Покажется только если
        # у Блока А все score~0 (порог Max Score < 20).
        await update_report_status(db, report_id, "competitor_discovery", progress=58)
        from app.core.competitor_finder import extract_ai_mentioned_in_niche
        try:
            ai_mentioned, ai_mentioned_meta = await extract_ai_mentioned_in_niche(
                raw_responses,
                niche,
                brand_name=report.brand_name,
                existing_block_a=competitors or [],
                count=settings.COMPETITORS_PER_REPORT,
            )
        except Exception as exc:
            logger.warning("ai_mentioned_in_niche_failed", error=str(exc))
            ai_mentioned = []
            ai_mentioned_meta = {}

        # Сохраняем оба списка + sources_map в niche_data (без новой миграции).
        try:
            _niche_with = dict(niche or {})
            _niche_with["competitor_sources"] = competitor_sources_map or {}
            _niche_with["ai_mentioned_in_niche"] = ai_mentioned
            _niche_with["ai_mentioned_meta"] = ai_mentioned_meta or {}
            # Сохраняем citations AI Overview для прозрачности/повторного использования.
            _cits = locals().get("ai_citations")
            if _cits:
                _niche_with["ai_citations"] = _cits
            await update_report_field(
                db, report_id,
                niche_data=_niche_with,
                competitors=competitors,
                competitors_source=competitors_source,
            )
            niche = _niche_with
        except Exception as exc:
            logger.warning("ai_mentioned_save_failed", error=str(exc))
            await update_report_field(
                db, report_id,
                competitors=competitors,
                competitors_source=competitors_source,
            )

        # ===== ШАГ 5.6: Анализ сайтов клиента и конкурентов (Этап 2 ТЗ) =====
        # Делаем параллельно, исключения внутри analyze_site не роняют pipeline.
        await update_report_status(db, report_id, "site_analysis", progress=64)
        try:
            # URL конкурентов через XMLRiver — у нас только имена.
            url_tasks = [find_competitor_url(name, report.region) for name in (competitors or [])]
            urls = await asyncio.gather(*url_tasks, return_exceptions=True)
            competitor_urls: list[dict] = []
            sites_to_analyse: list[tuple[str, str]] = []  # (name, url)
            for name, url_result in zip(competitors or [], urls):
                url = url_result if isinstance(url_result, str) else None
                competitor_urls.append({"name": name, "url": url})
                if url:
                    sites_to_analyse.append((name, url))

            # Параллельный анализ: клиент + все конкуренты с найденным URL
            site_tasks = [analyze_site(report.url)] + [
                analyze_site(url) for _, url in sites_to_analyse
            ]
            site_results = await asyncio.gather(*site_tasks, return_exceptions=True)

            client_site_analysis = (
                site_results[0]
                if site_results and not isinstance(site_results[0], Exception)
                else None
            )
            competitors_site_analysis = []
            # Итерация-2, А3: меняем generic-«названия» конкурентов (SEO-фразы
            # из выдачи) на РЕАЛЬНЫЕ названия компаний, извлечённые с их сайтов.
            from app.core.site_analyzer import looks_generic_name
            name_remap: dict[str, str] = {}
            client_brand_l = (report.brand_name or "").strip().lower()
            for (orig_name, _url), res in zip(sites_to_analyse, site_results[1:]):
                if isinstance(res, Exception):
                    logger.warning("site_analyze_one_failed", error=str(res))
                    continue
                competitors_site_analysis.append(res)
                org_name = (res.get("org_name") or "").strip() if isinstance(res, dict) else ""
                # Переименовываем, если нашли конкретное имя и оно лучше исходного:
                # исходное generic, либо отличается и само не generic.
                if (
                    org_name
                    and not looks_generic_name(org_name)
                    and org_name.lower() != orig_name.lower()
                    and org_name.lower() != client_brand_l
                    and (looks_generic_name(orig_name) or len(org_name) <= len(orig_name) + 4)
                ):
                    name_remap[orig_name] = org_name

            if name_remap:
                # Применяем к списку конкурентов и к competitor_urls, дедуп по имени.
                seen_l: set[str] = set()
                renamed: list[str] = []
                for c in (competitors or []):
                    new = name_remap.get(c, c)
                    if new.lower() in seen_l or new.lower() == client_brand_l:
                        continue
                    seen_l.add(new.lower())
                    renamed.append(new)
                competitors = renamed
                for cu in competitor_urls:
                    cu["name"] = name_remap.get(cu.get("name"), cu.get("name"))
                await update_report_field(db, report_id, competitors=competitors)
                logger.info("competitors_renamed_from_sites", remap=name_remap)

            # Лидер по SoV — определим позже, пока передаём None,
            # gap_analyzer возьмёт первого с fetched=True.
            gap = build_gap_analysis(
                client_site_analysis,
                competitors_site_analysis,
                competitor_urls,
                leader_name=None,
            )

            # Срочный фикс 3.3: фактчек релевантности конкурентов.
            # Если источник — llm_fallback (модель «из головы») или у <3 конкурентов
            # не нашёлся живой сайт — помечаем отчёт флагом и подсветим эксперту.
            urls_found = sum(1 for c in competitor_urls if c.get("url"))
            # «sparse» (Итерация-3) — честный сигнал «ниша свободна», тоже подсвечиваем эксперту.
            competitor_quality_low = (
                competitors_source in ("llm_fallback", "sparse") or urls_found < 3
            )

            await update_report_field(
                db,
                report_id,
                competitor_urls=competitor_urls,
                client_site_analysis=client_site_analysis,
                competitors_site_analysis=competitors_site_analysis,
                gap_analysis=gap,
                competitor_quality_low=competitor_quality_low,
            )
            if competitor_quality_low:
                logger.warning(
                    "competitor_quality_low",
                    report_id=str(report_id),
                    source=competitors_source,
                    urls_found=urls_found,
                )
        except Exception as exc:
            logger.error("site_analysis_step_failed", error=str(exc), error_type=type(exc).__name__)
            # Не блокируем pipeline — без site-analysis отчёт всё равно собирается.

        # ===== ШАГ 6: Анализ упоминаний (по тем же ответам, что уже опросили) =====
        # ВСЕ бренды разом: клиент + Блок А (прямые из выдачи) + Блок Б
        # (кого ИИ называет в нише). Так у нас единый согласованный список,
        # без рассинхрона «нашли одних, ищем других» (MD2 Часть 1).
        await update_report_status(db, report_id, "analyzing_responses", progress=70)
        all_brands = [report.brand_name] + (competitors or []) + (ai_mentioned or [])
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

            # Этап 4.2 ТЗ: письмо + follow-up цепочка.
            from app.core.report_delivery import finalize_report_delivery
            await finalize_report_delivery(db, report_final)

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
