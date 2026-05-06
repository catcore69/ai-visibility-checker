import json
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.core.llm_prompts import COMPETITOR_FINDER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def find_competitors(niche: dict[str, Any], brand_name: str, count: int = 5) -> list[str]:
    """Подбирает 5 главных конкурентов (1 LLM-вызов)."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    prompt = COMPETITOR_FINDER_PROMPT.format(
        category=niche.get("category", ""),
        subcategory=niche.get("subcategory", ""),
        region=niche.get("region", ""),
        target_audience_description=niche.get("target_audience_description", ""),
        brand_name=brand_name,
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )

    raw = response.choices[0].message.content or "[]"

    try:
        # Очищаем от возможных markdown-блоков
        raw = raw.strip().strip("```json").strip("```").strip()
        competitors: list[str] = json.loads(raw)
        competitors = [c for c in competitors if c and c != brand_name][:count]
    except (json.JSONDecodeError, TypeError):
        logger.error("competitor_finder_json_error", raw=raw[:200])
        competitors = []

    logger.info("competitors_found", count=len(competitors), brand=brand_name)
    return competitors
