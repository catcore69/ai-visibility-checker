import json
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.core.llm_prompts import NICHE_DETECTOR_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def detect_niche(url: str, brand_name: str, region: str) -> dict[str, Any]:
    """Определяет нишу бизнеса через LLM (1 вызов)."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    prompt = NICHE_DETECTOR_PROMPT.format(
        url=url, brand_name=brand_name, region=region
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=600,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content or "{}"

    try:
        niche_data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("niche_detector_json_error", raw=raw[:200])
        niche_data = {
            "category": "Бизнес",
            "subcategory": "Общее",
            "region": region,
            "target_audience": "B2C",
            "target_audience_description": "потребители",
            "language": "ru",
            "is_local": False,
            "typical_user_questions": [],
        }

    logger.info("niche_detected", category=niche_data.get("category"), brand=brand_name)
    return niche_data
