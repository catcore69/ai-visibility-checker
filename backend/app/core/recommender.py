import json
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.core.llm_prompts import RECOMMENDATIONS_PROMPT
from app.core.scorer import get_weak_models, get_strong_models, get_top_sources
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def generate_recommendations(
    analysis: Any,
    niche: dict[str, Any],
    brand_name: str,
    score: int,
    presence_rate: int,
    competitors: list[str],
) -> list[dict]:
    """Генерирует 5 персонализированных рекомендаций (1 LLM-вызов)."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    weak_models = get_weak_models(analysis, brand_name)
    strong_models = get_strong_models(analysis, brand_name)
    top_sources = get_top_sources(analysis)

    # Топ конкуренты, у которых score > score клиента
    from app.core.scorer import compare_with_competitors, calculate_visibility_score
    all_brands = [brand_name] + competitors
    comparison = compare_with_competitors(analysis, brand_name, all_brands)
    better_competitors = [
        c["brand_name"] for c in comparison
        if not c["is_client"] and c["score"] > score
    ][:3]

    prompt = RECOMMENDATIONS_PROMPT.format(
        brand_name=brand_name,
        category=niche.get("category", ""),
        subcategory=niche.get("subcategory", ""),
        region=niche.get("region", ""),
        score=score,
        presence_rate=presence_rate,
        weak_models=", ".join(weak_models) or "нет",
        strong_models=", ".join(strong_models) or "нет",
        top_competitors=", ".join(better_competitors) or "нет",
        top_sources=", ".join(top_sources[:5]) or "нет",
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
        recommendations: list[dict] = data.get("recommendations", [])
    except json.JSONDecodeError:
        logger.error("recommender_json_error", raw=raw[:200])
        recommendations = []

    logger.info("recommendations_generated", count=len(recommendations))
    return recommendations
