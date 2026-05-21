import json
import xml.etree.ElementTree as ET
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.core.llm_prompts import COMPETITOR_FINDER_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Хосты, которые не считаем сайтом конкурента (агрегаторы, маркетплейсы, соцсети).
# Когда ищем сайт по имени бренда через SERP — пропускаем эти результаты.
_COMPETITOR_URL_BLACKLIST = {
    "vk.com", "instagram.com", "facebook.com", "ok.ru", "youtube.com",
    "t.me", "twitter.com", "x.com", "tiktok.com",
    "ozon.ru", "wildberries.ru", "wb.ru", "avito.ru", "youla.ru",
    "drom.ru", "auto.ru", "cian.ru", "yandex.market", "market.yandex.ru",
    "sbermegamarket.ru", "megamarket.ru",
    "2gis.ru", "yandex.ru", "ya.ru", "google.com", "google.ru",
    "tripadvisor.ru", "tripadvisor.com", "booking.com", "ostrovok.ru",
    "wikipedia.org", "ru.wikipedia.org",
}


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _is_blacklisted_host(host: str) -> bool:
    for b in _COMPETITOR_URL_BLACKLIST:
        if host == b or host.endswith("." + b):
            return True
    return False


async def find_competitor_url(name: str, region: str = "Россия") -> Optional[str]:
    """Ищет официальный сайт конкурента через XMLRiver SERP.

    Возвращает URL первого результата, не принадлежащего агрегатору.
    None — если не нашли или XMLRiver недоступен.
    """
    name = (name or "").strip()
    if not name:
        return None
    if not settings.XMLRIVER_USER or not settings.XMLRIVER_KEY:
        logger.warning("find_competitor_url_no_xmlriver_creds")
        return None

    lr = (
        settings.XMLRIVER_REGION_BY
        if "беларус" in region.lower() or "by" in region.lower()
        else settings.XMLRIVER_REGION_RU
    )
    query = f"{name} официальный сайт"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                "https://xmlriver.com/search/xml",
                params={
                    "user": settings.XMLRIVER_USER,
                    "key": settings.XMLRIVER_KEY,
                    "query": query,
                    "groupby": "10",
                    "lr": lr,
                },
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("find_competitor_url_serp_error", name=name, error=str(exc))
        return None

    try:
        root = ET.fromstring(response.text)
        for doc in root.findall(".//doc"):
            url_el = doc.find("url")
            if url_el is None or not url_el.text:
                continue
            url = url_el.text.strip()
            host = _domain_of(url)
            if not host or _is_blacklisted_host(host):
                continue
            # Берём только корень домена (без длинных путей с трекингом)
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}/"
    except ET.ParseError as exc:
        logger.warning("find_competitor_url_parse_error", name=name, error=str(exc))

    return None


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
