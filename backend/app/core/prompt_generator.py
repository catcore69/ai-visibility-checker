"""Генератор промптов для опроса ИИ-моделей.

Этап 1.3 ТЗ: вместо генерации каждый раз с `temperature=0.7` (что даёт
несравнимые отчёты внутри одной ниши) — детерминированный кеш в таблице
`niche_prompt_templates`. Первый отчёт в нише генерирует 10 промптов и
сохраняет их по ключу slugify(category+subcategory+region+target_audience).
Все последующие отчёты в этой же нише берут готовые промпты из БД —
дешевле LLM-вызовов, и цифры между клиентами становятся сравнимыми.

Через 2–3 месяца естественно накапливается библиотека по 20–30 нишам.
"""

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Optional

import httpx
from openai import AsyncOpenAI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm_prompts import PROMPT_GENERATOR_PROMPT, REAL_QUERIES_SELECTOR_PROMPT
from app.db.models.niche_prompt_template import NichePromptTemplate
from app.db.session import AsyncSessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _slugify(text: str) -> str:
    """Грубый slugify для построения детерминированного ключа ниши.

    Не транслитерируем — кириллицу оставляем как есть, потом всё в lower.
    Постгрес умеет хранить utf-8 в TEXT, проблем нет.
    """
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^\w\-_]", "", text, flags=re.UNICODE)
    return text or "unknown"


def _niche_key(niche: dict[str, Any]) -> str:
    category = _slugify(niche.get("category", ""))
    subcategory = _slugify(niche.get("subcategory", ""))
    region = _slugify(niche.get("region", ""))
    audience = _slugify(niche.get("target_audience", ""))
    return f"{category}|{subcategory}|{region}|{audience}"


_TEMPLATE_RESIDUE_PATTERNS = (
    "x или y",     # буквальный плейсхолдер
    " x ", " y ",  # одиночные плейсхолдеры
    "сравнение:",  # шаблонный префикс
    "рекомендация:",
    "{",  # незаполненная переменная промпта
    "}",
)


def _looks_like_template_residue(prompts: list[str]) -> bool:
    """True, если в списке промптов есть следы LLM-шаблонов («X или Y:», и др.)
    или незаполненные плейсхолдеры. Используется как инвалидатор кеша:
    после улучшения промптов мы не хотим показывать старые шаблонные запросы."""
    for p in prompts or []:
        if not isinstance(p, str):
            continue
        pl = p.lower()
        for marker in _TEMPLATE_RESIDUE_PATTERNS:
            if marker in pl:
                return True
    return False


async def _load_cached_prompts(niche_key: str) -> Optional[list[str]]:
    """Читает промпты из niche_prompt_templates по ключу."""
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(NichePromptTemplate).where(
                NichePromptTemplate.niche_key == niche_key
            )
            result = await db.execute(stmt)
            row = result.scalars().first()
            if row and isinstance(row.prompts, list) and row.prompts:
                return [p for p in row.prompts if isinstance(p, str) and p.strip()]
    except Exception as exc:
        logger.warning("prompt_cache_load_error", error=str(exc), niche_key=niche_key)
    return None


async def _delete_cached_prompts(niche_key: str) -> None:
    """Удаляет стейл-запись кеша (для инвалидации шаблонного мусора)."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(NichePromptTemplate).where(NichePromptTemplate.niche_key == niche_key)
            )
            await db.commit()
    except Exception as exc:
        logger.warning("prompt_cache_delete_error", niche_key=niche_key, error=str(exc))


async def _save_cached_prompts(
    niche_key: str,
    niche: dict[str, Any],
    prompts: list[str],
) -> None:
    """Сохраняет промпты в niche_prompt_templates для будущих клиентов в той же нише."""
    try:
        async with AsyncSessionLocal() as db:
            template = NichePromptTemplate(
                niche_key=niche_key,
                category=str(niche.get("category", ""))[:500],
                subcategory=str(niche.get("subcategory", ""))[:500] or None,
                region=str(niche.get("region", ""))[:500] or None,
                target_audience=str(niche.get("target_audience", ""))[:500] or None,
                prompts=prompts,
            )
            db.add(template)
            await db.commit()
            logger.info("prompt_cache_saved", niche_key=niche_key, count=len(prompts))
    except Exception as exc:
        # Возможно конкурентный insert — не критично, просто читаем в след. раз.
        logger.warning("prompt_cache_save_error", error=str(exc), niche_key=niche_key)


async def _google_suggest(query: str, hl: str = "ru") -> list[str]:
    """Бесплатные автоподсказки Google (открытый эндпоинт, без авторизации).
    Возвращает строки, которые предлагает Google при наборе запроса.
    """
    if not query or not query.strip():
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                "https://suggestqueries.google.com/complete/search",
                params={"client": "firefox", "q": query, "hl": hl},
            )
            r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [s for s in data[1] if isinstance(s, str)][:20]
    except Exception as exc:
        logger.warning("google_suggest_error", query=query[:60], error=str(exc))
    return []


def _city_from_region(region: str) -> str:
    """«Минск, Беларусь» → «Минск»; «Витебск, Беларусь» → «Витебск»."""
    if not region:
        return ""
    first = region.split(",")[0].strip()
    # Если это название страны — города нет.
    if first.lower() in ("россия", "беларусь", "рф", "рб", "украина", "казахстан"):
        return ""
    return first


def _build_query_seeds(niche: dict[str, Any]) -> list[str]:
    """Сиды для автоподсказок. Приоритет: subcategory (узкая ниша) → category
    (общая). Раньше брали только category, и магазин аккумуляторов
    (subcategory=«Аккумуляторы для транспорта», category=«Автоаксессуары»)
    получал подсказки про автоаксессуары (мимо темы). Subcategory всегда
    конкретнее — у живых suggest-движков она даёт релевантные подсказки.
    """
    cat = (niche.get("category") or "").strip()
    sub = (niche.get("subcategory") or "").strip()
    region = (niche.get("region") or "").strip()
    city = (niche.get("city") or "").strip() or _city_from_region(region)
    country_part = region.split(",")[-1].strip() if "," in region else ""

    # Базовая узкая ниша = subcategory если есть, иначе category.
    primary = sub or cat
    secondary = cat if sub else ""  # category как widening, только если subcategory была.

    seeds: list[str] = []
    if primary:
        if city:
            seeds.append(f"{primary} {city}")
        if country_part and country_part.lower() not in ("", "рф", "рб"):
            seeds.append(f"{primary} {country_part}")
        seeds.append(primary)
    # category для расширения, если есть отличие
    if secondary and secondary.lower() != primary.lower():
        if city:
            seeds.append(f"{secondary} {city}")

    # Дедуп с сохранением порядка
    seen: set[str] = set()
    out: list[str] = []
    for s in seeds:
        sl = s.strip().lower()
        if sl and sl not in seen:
            seen.add(sl)
            out.append(s)
    return out


async def _xmlriver_tips_batch(phrases: list[str], region: str = "") -> list[str]:
    """Реальные поисковые подсказки через XMLRiver api-tips (правильный эндпоинт).

    Документация: POST на /search/xml с setab=tips + гео-параметрами + JSON-body.
    ВНИМАНИЕ: оплата ЗА КАЖДУЮ фразу в запросе (батчим осторожно). Логируем
    sent_phrases, чтобы контролировать расходы.
    """
    if not settings.XMLRIVER_USER or not settings.XMLRIVER_KEY:
        return []
    phrases = [p for p in (phrases or []) if p and p.strip()][:50]
    if not phrases:
        return []
    # Гео-параметр lr берём по региону клиента (БЕЛОРУССКИЙ КЛИЕНТ → БЕЛОРУССКИЕ
    # ПОДСКАЗКИ, а не РФ по дефолту). Это критично для региональной релевантности.
    is_by = any(s in (region or "").lower() for s in ("беларус", "рб", "by"))
    lr = settings.XMLRIVER_REGION_BY if is_by else settings.XMLRIVER_REGION_RU
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.post(
                "https://xmlriver.com/search/xml",
                params={
                    "setab": "tips",
                    "user": settings.XMLRIVER_USER,
                    "key": settings.XMLRIVER_KEY,
                    "lr": lr,
                },
                json={"phrases": phrases},
            )
            resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("xmlriver_tips_error", count=len(phrases), error=str(exc))
        return []

    logger.info(
        "xmlriver_tips_sent",
        sent_phrases=len(phrases),  # ← по документации оплата ЗА КАЖДУЮ фразу
        lr=lr,
        region=region or "default",
    )

    if isinstance(data, dict):
        out = data.get("phrases") or data.get("tips") or []
    elif isinstance(data, list):
        out = data
    else:
        out = []
    return [s.strip() for s in out if isinstance(s, str) and s.strip()][:60]


async def _xmlriver_suggest(query: str, region: str = "") -> list[str]:
    """Совместимость со старой сигнатурой: одна фраза → tips-batch на 1 элемент.
    Внутри это уже корректный POST на /search/xml?setab=tips, не GET на /suggest/xml.
    """
    return await _xmlriver_tips_batch([query], region=region)


async def _xmlriver_wordstat(query: str) -> list[str]:
    """Реальные запросы из Яндекс.Wordstat через XMLRiver."""
    if not settings.XMLRIVER_USER or not settings.XMLRIVER_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=20.0) as c:
            resp = await c.get(
                "https://xmlriver.com/wordstat/xml",
                params={
                    "user": settings.XMLRIVER_USER,
                    "key": settings.XMLRIVER_KEY,
                    "query": query,
                },
            )
            resp.raise_for_status()
        root = ET.fromstring(resp.text)
        out: list[str] = []
        # Wordstat XMLRiver обычно отдаёт <word>фраза</word> + <shows>N</shows>.
        for w in root.iter():
            if (w.tag or "").lower() in ("word", "phrase", "query"):
                txt = (w.text or "").strip()
                if txt and 5 < len(txt) < 200:
                    out.append(txt)
        # Backup: любые текстовые узлы с пробелом.
        if not out:
            for el in root.iter():
                txt = (el.text or "").strip()
                if txt and " " in txt and 5 < len(txt) < 200:
                    out.append(txt)
        return out[:40]
    except Exception as exc:
        logger.warning("xmlriver_wordstat_error", query=query, error=str(exc))
        return []


async def _fetch_real_queries(niche: dict[str, Any]) -> list[str]:
    """Итерация-3, Задача 2 (ТЗ-1.1): реальные поисковые запросы людей.

    Источники (по убыванию приоритета): Google suggest (открытый эндпоинт),
    Яндекс suggest через XMLRiver, Яндекс Wordstat через XMLRiver (для РФ).
    Каждый источник опрашиваем по НЕСКОЛЬКИМ сидам (категория+город, категория
    +страна, голая категория). LLM здесь не участвует.
    """
    seeds = _build_query_seeds(niche)
    if not seeds:
        return []

    # До 6 сидов — иначе много запросов в suggest-эндпоинты.
    seeds = seeds[:6]
    region_l = (niche.get("region") or "").lower()
    is_rf = "росси" in region_l or "рф" in region_l

    region = niche.get("region", "") or ""
    tasks: list = []
    # Google suggest — отдельные запросы (открытый API, без оплаты за фразу).
    for seed in seeds:
        tasks.append(_google_suggest(seed))
    # Яндекс tips — ОДИН батч-POST на все сиды (оплата всё равно за фразу,
    # но HTTP-запрос один, плюс гео-параметр прокидывается из региона клиента).
    tasks.append(_xmlriver_tips_batch(seeds, region=region))
    # Wordstat доступен только для РФ-регионов (по конфигу XMLRiver).
    if is_rf:
        for seed in seeds[:3]:
            tasks.append(_xmlriver_wordstat(seed))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    raw: list[str] = []
    for src in results:
        if isinstance(src, list):
            raw.extend(src)

    # Чистка + дедуп с сохранением порядка. НЕ выкидываем сам сид — он часто
    # тоже валидный запрос («бухгалтерские услуги витебск»).
    seen: set[str] = set()
    out: list[str] = []
    for q in raw:
        q_clean = re.sub(r"\s+", " ", q).strip(" .,;:!?")
        if not q_clean or len(q_clean) < 5 or len(q_clean) > 200:
            continue
        if q_clean.lower() in ("найти", "купить", "цена"):
            continue
        nl = q_clean.lower()
        if nl in seen:
            continue
        seen.add(nl)
        out.append(q_clean)

    logger.info(
        "real_queries_fetched",
        seeds=len(seeds),
        google_yandex_calls=len(seeds) * 2,
        wordstat_calls=(len(seeds[:3]) if is_rf else 0),
        raw=len(raw),
        unique=len(out),
    )
    return out


async def _select_real_queries(
    niche: dict[str, Any], real_queries: list[str], count: int, brand_name: str = ""
) -> list[str]:
    """ТЗ-2: LLM ОТБИРАЕТ из реальных, ничего не сочиняя. После ответа
    валидируем: каждый запрос должен быть ДОСЛОВНО в `real_queries`.
    Запросы, которых там нет → LLM их переформулировала → отбрасываем."""
    if not real_queries:
        return []
    # Если реальных и так мало — отдаём как есть, LLM не нужна.
    if len(real_queries) <= count:
        return real_queries

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    lines = "\n".join(f"- {q}" for q in real_queries[:80])
    prompt = REAL_QUERIES_SELECTOR_PROMPT.format(
        category=niche.get("category", ""),
        region=niche.get("region", ""),
        target_audience_description=niche.get("target_audience_description", ""),
        brand_name=brand_name or niche.get("brand", ""),
        count=count,
        real_queries=lines,
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.MODEL_TEXT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,  # детерминированно — мы только отбираем
            max_tokens=800,
        )
        raw = (resp.choices[0].message.content or "[]").strip()
        raw = raw.strip("```json").strip("```").strip()
        items = json.loads(raw) if raw else []
        if not isinstance(items, list):
            items = []
    except Exception as exc:
        logger.warning("real_queries_select_error", error=str(exc))
        items = []

    # ВАЛИДАЦИЯ ДОСЛОВНОСТИ: запрос должен быть в исходном списке (lowercase + норма пробелов).
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip()).lower()
    real_index = {norm(q): q for q in real_queries}
    validated: list[str] = []
    rejected = 0
    for q in items:
        if not isinstance(q, str):
            continue
        key = norm(q)
        if key in real_index:
            validated.append(real_index[key])
        else:
            rejected += 1
    logger.info(
        "real_queries_selected",
        returned_by_llm=len(items),
        validated=len(validated),
        rejected_as_invented=rejected,
    )
    # Если LLM «креативила» и валидных < половины count — берём первые N из реальных
    # напрямую (порядок суггеста — это уже частотность поиска).
    if len(validated) < max(3, count // 2):
        logger.warning("llm_selector_unreliable_fallback_to_head", count=count)
        # Дополним из real_queries уникальными головными, сохранив имеющиеся валидированные.
        seen = {norm(q) for q in validated}
        for q in real_queries:
            if norm(q) not in seen:
                validated.append(q)
                seen.add(norm(q))
            if len(validated) >= count:
                break
    return validated[:count]


async def _generate_via_llm(niche: dict[str, Any], count: int) -> list[str]:
    """Один LLM-вызов на генерацию промптов."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    prompt = PROMPT_GENERATOR_PROMPT.format(
        category=niche.get("category", ""),
        subcategory=niche.get("subcategory", ""),
        region=niche.get("region", ""),
        target_audience_description=niche.get("target_audience_description", ""),
    )

    try:
        response = await client.chat.completions.create(
            model=settings.MODEL_TEXT,
            messages=[{"role": "user", "content": prompt}],
            # Низкая температура → промпты для одной ниши получаются ближе
            # друг к другу, но кеш делает это окончательно детерминированным.
            temperature=0.3,
            max_tokens=800,
        )
        raw = response.choices[0].message.content or "[]"
    except Exception as exc:
        logger.error("prompt_generator_llm_error", error=str(exc))
        return []

    try:
        raw = raw.strip().strip("```json").strip("```").strip()
        items = json.loads(raw)
        if not isinstance(items, list):
            return []
        return [p.strip() for p in items if isinstance(p, str) and p.strip()][:count]
    except (json.JSONDecodeError, TypeError):
        logger.error("prompt_generator_json_error", raw=raw[:200])
        return []


async def generate_prompts(niche: dict[str, Any], count: int = 10) -> list[str]:
    """Возвращает 10 промптов для опроса LLM-моделей.

    Алгоритм (Этап 1.3 ТЗ):
    1. Строим детерминированный ключ ниши.
    2. Смотрим в niche_prompt_templates — если есть, берём оттуда (без LLM).
    3. Если нет — генерируем через LLM, сохраняем в БД, возвращаем.
    4. На fallback — typical_user_questions из ниша-детектора.
    """
    niche_key = _niche_key(niche)

    cached = await _load_cached_prompts(niche_key)
    if cached and len(cached) >= max(count - 2, 5) and not _looks_like_template_residue(cached):
        logger.info("prompts_from_cache", niche_key=niche_key, count=len(cached))
        return cached[:count]
    if cached and _looks_like_template_residue(cached):
        logger.warning("cache_invalidated_template_artifacts", niche_key=niche_key, count=len(cached))
        # Удаляем стейл-запись, чтобы _save_cached_prompts смог записать свежие.
        await _delete_cached_prompts(niche_key)

    # Итерация-3, Задача 2 (ТЗ): запросы — ИЗ РЕАЛЬНЫХ подсказок.
    # LLM здесь только ОТБИРАЕТ ДОСЛОВНО из списка (с валидацией). Никаких
    # добивок шаблонной генерацией до полного count. Лучше 5 реальных, чем
    # 5 реальных + 5 выдуманных. На LLM-fallback идём только если реальных <3
    # (совсем нишевый регион / suggest-эндпоинты молчат).
    prompts: list[str] = []
    try:
        real = await _fetch_real_queries(niche)
        if len(real) >= 3:
            prompts = await _select_real_queries(niche, real, count)
            logger.info(
                "prompts_from_real_queries",
                niche_key=niche_key,
                real_pool=len(real),
                returned=len(prompts),
            )
    except Exception as exc:
        logger.warning("real_queries_pipeline_failed", error=str(exc))

    if not prompts:
        # Совсем не нашли реальных подсказок — крайний случай.
        prompts = await _generate_via_llm(niche, count)
        logger.warning("prompts_template_fallback_used", niche_key=niche_key, count=len(prompts))

    if prompts and len(prompts) >= 5:
        # Сохраняем только если получили достаточное число — мусор не кешируем.
        await _save_cached_prompts(niche_key, niche, prompts)
        logger.info("prompts_generated_and_cached", niche_key=niche_key, count=len(prompts))
        return prompts[:count]

    # Fallback: типичные вопросы из ниша-детектора
    fallback = [
        q for q in (niche.get("typical_user_questions") or [])
        if isinstance(q, str) and q.strip()
    ][:count]
    if fallback:
        logger.warning("prompts_fallback_to_niche_questions", niche_key=niche_key, count=len(fallback))
        return fallback

    logger.error("prompts_empty", niche_key=niche_key)
    return []
