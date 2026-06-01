import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import AsyncOpenAI
from rapidfuzz import fuzz

from app.config import settings
from app.core.llm_prompts import MENTION_ANALYZER_PROMPT
from app.llm_pollers.base import LLMResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MentionResult:
    model_name: str
    prompt: str
    brand_name: str
    mentioned: bool
    position: int = 0
    sentiment: str = "neutral"
    context: str = ""
    is_recommendation: bool = False
    citations: list[str] = field(default_factory=list)


@dataclass
class Analysis:
    results: list[MentionResult] = field(default_factory=list)
    all_citations: list[str] = field(default_factory=list)

    @property
    def total_prompts(self) -> int:
        prompts = {r.prompt for r in self.results}
        return len(prompts)

    @property
    def total_models(self) -> int:
        models = {r.model_name for r in self.results}
        return len(models)

    @property
    def all_results(self) -> list[MentionResult]:
        return self.results

    def get_brand_results(self, brand_name: str) -> list[MentionResult]:
        return [r for r in self.results if r.brand_name == brand_name]

    def add_result(self, model_name: str, prompt: str, brand_results: list[dict], citations: list[str]) -> None:
        for br in brand_results:
            self.results.append(
                MentionResult(
                    model_name=model_name,
                    prompt=prompt,
                    brand_name=br.get("name", ""),
                    mentioned=br.get("mentioned", False),
                    position=br.get("position", 0),
                    sentiment=br.get("sentiment", "neutral"),
                    context=br.get("context", ""),
                    is_recommendation=br.get("is_recommendation", False),
                    citations=citations,
                )
            )
        self.all_citations.extend(citations)

    def add_empty(self, model_name: str, prompt: str, brands: list[str]) -> None:
        for brand in brands:
            self.results.append(
                MentionResult(
                    model_name=model_name,
                    prompt=prompt,
                    brand_name=brand,
                    mentioned=False,
                )
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [
                {
                    "model_name": r.model_name,
                    "prompt": r.prompt,
                    "brand_name": r.brand_name,
                    "mentioned": r.mentioned,
                    "position": r.position,
                    "sentiment": r.sentiment,
                    "context": r.context,
                    "is_recommendation": r.is_recommendation,
                    "citations": r.citations,
                }
                for r in self.results
            ],
            "all_citations": self.all_citations,
        }


async def _analyze_mention_with_llm(
    response_text: str,
    brands: list[str],
    prompt: str,
) -> tuple[list[dict], list[str]]:
    """LLM-as-judge: точный анализ упоминаний."""
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    llm_prompt = MENTION_ANALYZER_PROMPT.format(
        prompt=prompt,
        response_text=response_text[:2000],  # обрезаем если слишком длинный
        brands_json=json.dumps(brands, ensure_ascii=False),
    )

    try:
        response = await client.chat.completions.create(
            model=settings.MODEL_ANALYSIS,
            messages=[{"role": "user", "content": llm_prompt}],
            temperature=0,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        brand_results: list[dict] = data.get("brands", [])
        citations: list[str] = data.get("citations", [])
        # Итерация-3: апгрейд тональности на основе is_recommendation.
        # Если ИИ РЕКОМЕНДУЕТ бренд (а не просто перечислил) — это позитивный
        # сигнал, даже если LLM-as-judge поставил neutral. Симметрично:
        # negative оставляем как есть (явный негатив сильнее рекомендации).
        for br in brand_results:
            if not br.get("mentioned"):
                continue
            sent = br.get("sentiment", "neutral")
            if br.get("is_recommendation") and sent == "neutral":
                br["sentiment"] = "positive"
        return brand_results, citations
    except Exception as exc:
        logger.error("mention_analyzer_error", error=str(exc))
        return [], []


async def analyze_responses(
    raw_responses: dict[str, dict[str, LLMResponse]],
    brands: list[str],
) -> Analysis:
    """
    Двухэтапный анализ ответов всех моделей:
    1. Regex/fuzzy match — быстро и бесплатно.
    2. LLM-as-judge — только для подтверждённых упоминаний.
    """
    analysis = Analysis()
    sem = asyncio.Semaphore(5)  # Ограничиваем параллельные LLM-as-judge вызовы

    # ФИКС 3: для каждого бренда заранее считаем «ядро» — чтобы матч
    # «База отдыха "Золотая Рыбка"» работал, когда ИИ называет
    # «Золотая Рыбка». Префиксы-категории/юр.формы/кавычки убираем
    # ТОЛЬКО для сравнения; в отчёте остаётся полное имя.
    from app.core.site_analyzer import normalize_brand_for_match
    brand_cores = {b: normalize_brand_for_match(b) or b.lower() for b in brands}

    async def process_one(model_name: str, prompt: str, llm_response: LLMResponse) -> None:
        if llm_response.error or not llm_response.response_text:
            analysis.add_empty(model_name, prompt, brands)
            return

        text = llm_response.response_text
        text_low = text.lower()

        # ШАГ 1: Быстрый regex/fuzzy поиск — по ЯДРУ имени, не по полному.
        potentially_mentioned = []
        words = None  # ленивый split
        for brand in brands:
            core = brand_cores[brand]
            if core and core in text_low:
                potentially_mentioned.append(brand)
                continue
            # Полное имя как fallback (некоторые ИИ могут писать с префиксом).
            if brand.lower() in text_low:
                potentially_mentioned.append(brand)
                continue
            # Fuzzy по словам, по ядру.
            if not core or len(core) < 3:
                continue
            if words is None:
                words = re.findall(r'\b\w{3,}\b', text)
            for word in words:
                if fuzz.ratio(core, word.lower()) > 85:
                    potentially_mentioned.append(brand)
                    break

        # ШАГ 2: LLM-as-judge только если что-то найдено
        if potentially_mentioned:
            async with sem:
                brand_results, citations = await _analyze_mention_with_llm(
                    text, brands, prompt
                )
            if brand_results:
                analysis.add_result(model_name, prompt, brand_results, citations)
                return

        # Никто не упомянут
        analysis.add_empty(model_name, prompt, brands)

    tasks = []
    for model_name, prompt_responses in raw_responses.items():
        for prompt, llm_response in prompt_responses.items():
            tasks.append(process_one(model_name, prompt, llm_response))

    await asyncio.gather(*tasks)
    return analysis
