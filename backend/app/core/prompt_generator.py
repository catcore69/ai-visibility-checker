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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.llm_prompts import PROMPT_GENERATOR_PROMPT, REAL_QUERIES_GROUPER_PROMPT
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


async def _xmlriver_suggest(query: str) -> list[str]:
    """Реальные автоподсказки поиска через XMLRiver. Возвращает список фраз."""
    if not settings.XMLRIVER_USER or not settings.XMLRIVER_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.get(
                "https://xmlriver.com/suggest/xml",
                params={
                    "user": settings.XMLRIVER_USER,
                    "key": settings.XMLRIVER_KEY,
                    "query": query,
                },
            )
            resp.raise_for_status()
        root = ET.fromstring(resp.text)
        # XML может быть {<root><sug>фраза</sug><sug>...</sug></root>} или иначе —
        # берём ВСЕ текстовые узлы listа.
        out: list[str] = []
        for el in root.iter():
            txt = (el.text or "").strip()
            if txt and len(txt) > 5 and len(txt) < 200 and " " in txt:
                out.append(txt)
        return out[:30]
    except Exception as exc:
        logger.warning("xmlriver_suggest_error", query=query, error=str(exc))
        return []


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
    """Итерация-3, Задача 2: реальные поисковые запросы вместо LLM-шаблонов.

    Источники: автоподсказки поиска (XMLRiver suggest) + Яндекс.Wordstat.
    Дедуп, чистка, ограничение длины. Дальше LLM только сгруппирует и отберёт 10.
    """
    category = niche.get("category", "").strip()
    if not category:
        return []
    # Точка отсчёта — категория + город (если есть).
    city = (niche.get("region", "") or "").split(",")[0].strip()
    base = f"{category} {city}".strip() if city and "беларус" not in city.lower() and "росси" not in city.lower() else category

    sug_task = _xmlriver_suggest(base)
    ws_task = _xmlriver_wordstat(base)
    # Доп.вариант — без города, общее по нише (если регион нишевый).
    sug2_task = _xmlriver_suggest(category) if city else asyncio.sleep(0, result=[])
    sug, ws, sug2 = await asyncio.gather(sug_task, ws_task, sug2_task, return_exceptions=True)

    raw: list[str] = []
    for src in (sug, ws, sug2):
        if isinstance(src, list):
            raw.extend(src)

    # Чистка + дедуп с сохранением порядка.
    seen: set[str] = set()
    out: list[str] = []
    for q in raw:
        q_clean = re.sub(r"\s+", " ", q).strip(" .,;:!?")
        if not q_clean or len(q_clean) < 8 or len(q_clean) > 150:
            continue
        # Чисто статусные/слишком общие запросы убираем.
        if q_clean.lower() in ("найти", "купить", "цена"):
            continue
        nl = q_clean.lower()
        if nl in seen:
            continue
        seen.add(nl)
        out.append(q_clean)
    logger.info("real_queries_fetched", base=base, raw=len(raw), unique=len(out))
    return out


async def _group_real_queries_via_llm(
    niche: dict[str, Any], real_queries: list[str], count: int, brand_name: str = ""
) -> list[str]:
    """LLM только группирует/отбирает из РЕАЛЬНЫХ запросов — не выдумывает новые."""
    if not real_queries:
        return []
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    lines = "\n".join(f"- {q}" for q in real_queries[:60])  # ограничиваем длину промпта
    prompt = REAL_QUERIES_GROUPER_PROMPT.format(
        category=niche.get("category", ""),
        region=niche.get("region", ""),
        target_audience_description=niche.get("target_audience_description", ""),
        brand_name=brand_name or niche.get("brand", ""),
        real_queries=lines,
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.MODEL_TEXT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
        )
        raw = (resp.choices[0].message.content or "[]").strip()
        raw = raw.strip("```json").strip("```").strip()
        items = json.loads(raw)
        if isinstance(items, list):
            return [p.strip() for p in items if isinstance(p, str) and p.strip()][:count]
    except Exception as exc:
        logger.warning("real_queries_group_error", error=str(exc))
    return []


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
    if cached and len(cached) >= max(count - 2, 5):
        logger.info("prompts_from_cache", niche_key=niche_key, count=len(cached))
        return cached[:count]

    # Итерация-3, Задача 2: сначала пробуем РЕАЛЬНЫЕ запросы (suggest + wordstat),
    # LLM только группирует и отбирает 10. Если реальных недостаточно —
    # graceful fallback на LLM-генерацию по шаблонам.
    prompts: list[str] = []
    try:
        real = await _fetch_real_queries(niche)
        if len(real) >= 10:
            grouped = await _group_real_queries_via_llm(niche, real, count)
            if len(grouped) >= max(count - 2, 5):
                prompts = grouped
                logger.info("prompts_from_real_queries", niche_key=niche_key, count=len(prompts))
    except Exception as exc:
        logger.warning("real_queries_pipeline_failed", error=str(exc))

    if not prompts:
        prompts = await _generate_via_llm(niche, count)

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
