import json
from typing import Any, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.core.llm_prompts import NICHE_DETECTOR_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def detect_niche(
    url: str,
    brand_name: str,
    region: str,
    user_hint: Optional[str] = None,
) -> dict[str, Any]:
    """Определяет нишу бизнеса через LLM (1 вызов).

    Если задан `user_hint` — это явное описание ниши, которое клиент ввёл
    в форме. Подсказка имеет приоритет над тем, что LLM «угадывает» по URL.
    LLM в этом случае должна не выдумывать категорию, а структурировать
    подсказку клиента (subcategory, target_audience, language, …).
    """
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    hint_clean = (user_hint or "").strip()
    hint_block = (
        f"\n\nКЛИЕНТ САМ УКАЗАЛ НИШУ В ФОРМЕ: «{hint_clean}»\n"
        "Это АВТОРИТЕТНАЯ подсказка — используй её как `category`/`subcategory` "
        "и подбери остальные поля под неё. НЕ перепрыгивай в другую нишу, "
        "даже если на сайте мало контента или сайт пустой."
        if hint_clean
        else ""
    )

    prompt = NICHE_DETECTOR_PROMPT.format(
        url=url, brand_name=brand_name, region=region
    ) + hint_block

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
            "category": hint_clean or "Бизнес",
            "subcategory": hint_clean or "Общее",
            "region": region,
            "target_audience": "B2C",
            "target_audience_description": "потребители",
            "language": "ru",
            "is_local": False,
            "typical_user_questions": [],
        }

    # Гарантируем, что подсказка клиента не теряется и остаётся в JSON.
    if hint_clean:
        niche_data["user_hint"] = hint_clean
        # Если LLM всё-таки уехала в другую нишу (бывает) — насильно
        # переписываем category на то, что сказал клиент.
        cat = (niche_data.get("category") or "").lower()
        if hint_clean.lower() not in cat and cat not in hint_clean.lower():
            logger.warning(
                "niche_override_by_hint",
                llm_category=niche_data.get("category"),
                user_hint=hint_clean,
            )
            niche_data["category"] = hint_clean

    logger.info("niche_detected", category=niche_data.get("category"), brand=brand_name, hint=hint_clean or None)
    return niche_data
