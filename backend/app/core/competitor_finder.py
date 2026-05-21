import json
from typing import Any, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.core.llm_prompts import COMPETITOR_FINDER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _find_competitors_via_llm(
    niche: dict[str, Any],
    brand_name: str,
    count: int,
) -> list[str]:
    """Подбирает конкурентов через LLM (gpt-4o-mini)."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    prompt = COMPETITOR_FINDER_PROMPT.format(
        category=niche.get("category", ""),
        subcategory=niche.get("subcategory", ""),
        region=niche.get("region", ""),
        target_audience_description=niche.get("target_audience_description", ""),
        brand_name=brand_name,
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )
    except Exception as exc:
        logger.error("competitor_finder_llm_error", error=str(exc))
        return []

    raw = response.choices[0].message.content or "[]"
    try:
        raw = raw.strip().strip("```json").strip("```").strip()
        items = json.loads(raw)
        if not isinstance(items, list):
            return []
        return [c for c in items if isinstance(c, str) and c.strip() and c != brand_name][:count]
    except (json.JSONDecodeError, TypeError):
        logger.error("competitor_finder_json_error", raw=raw[:200])
        return []


def _merge_dedupe(client_list: list[str], llm_list: list[str], target: int) -> list[str]:
    """Объединяет два списка с приоритетом client_list, без дубликатов (без учёта регистра)."""
    seen: set[str] = set()
    out: list[str] = []
    for src in (client_list, llm_list):
        for item in src:
            key = item.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item.strip())
            if len(out) >= target:
                return out
    return out


async def find_competitors(
    niche: dict[str, Any],
    brand_name: str,
    count: int = 5,
    client_competitors: Optional[list[str]] = None,
) -> tuple[list[str], str]:
    """Подбирает конкурентов клиента.

    Возвращает (список, источник):
        ("client" / "mixed" / "llm").

    Логика (Этап 1.1 ТЗ):
    - Если клиент указал >=3 конкурентов в форме — используем их.
      Если их меньше {count}=5, добиваем LLM (источник "mixed").
      Если ровно {count} — источник "client" (LLM не зовём вообще).
    - Если клиент указал <3 (включая 0/None) — полностью LLM-подбор
      (источник "llm"). Считаем, что 1-2 ручных конкурента не статистически
      значимы и в любом случае нужны 5 для отчёта.
    """
    client_list = [c for c in (client_competitors or []) if c and c != brand_name][:count]

    if len(client_list) >= 3:
        if len(client_list) >= count:
            logger.info("competitors_from_client_only", count=len(client_list), brand=brand_name)
            return client_list[:count], "client"

        # Добиваем LLM до count
        need = count - len(client_list)
        llm_list = await _find_competitors_via_llm(niche, brand_name, need + 3)
        # Исключаем имена, которые уже указал клиент (с учётом регистра)
        client_lower = {c.lower() for c in client_list}
        llm_filtered = [c for c in llm_list if c.lower() not in client_lower]
        merged = _merge_dedupe(client_list, llm_filtered, count)
        logger.info(
            "competitors_mixed",
            client_count=len(client_list),
            llm_added=len(merged) - len(client_list),
            brand=brand_name,
        )
        return merged, "mixed"

    # Полностью LLM
    competitors = await _find_competitors_via_llm(niche, brand_name, count)
    logger.info("competitors_from_llm", count=len(competitors), brand=brand_name)
    return competitors, "llm"
