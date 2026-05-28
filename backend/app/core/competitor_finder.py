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


async def _xmlriver_search_results(query: str, region: str = "Россия", num: int = 20) -> list[dict]:
    """Сырые результаты поисковой выдачи через XMLRiver: [{title, url, domain}]."""
    if not settings.XMLRIVER_USER or not settings.XMLRIVER_KEY:
        return []
    lr = (
        settings.XMLRIVER_REGION_BY
        if ("беларус" in region.lower() or "by" in region.lower())
        else settings.XMLRIVER_REGION_RU
    )
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.get(
                "https://xmlriver.com/search/xml",
                params={
                    "user": settings.XMLRIVER_USER,
                    "key": settings.XMLRIVER_KEY,
                    "query": query,
                    "groupby": str(num),
                    "lr": lr,
                },
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("serp_search_error", query=query, error=str(exc))
        return []

    out: list[dict] = []
    try:
        root = ET.fromstring(response.text)
        for doc in root.findall(".//doc"):
            url_el = doc.find("url")
            title_el = doc.find("title")
            url = (url_el.text or "").strip() if url_el is not None else ""
            title = (title_el.text or "").strip() if title_el is not None else ""
            if not url:
                continue
            out.append({"title": title, "url": url, "domain": _domain_of(url)})
    except ET.ParseError as exc:
        logger.warning("serp_parse_error", query=query, error=str(exc))
    return out


async def _llm_extract_companies(
    candidates: list[dict],
    niche: dict[str, Any],
    exclude: list[str],
    count: int,
) -> list[str]:
    """Из выдачи извлекает названия реальных компаний-конкурентов в регионе.

    LLM выступает фильтром: «это компания, оказывающая {category} в {region},
    а не агрегатор/каталог/статья?» и нормализует название бренда.
    """
    if not candidates:
        return []
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)

    lines = "\n".join(f"- {c['title']} ({c['domain']})" for c in candidates[:20])
    exclude_str = ", ".join(exclude) if exclude else "—"
    prompt = (
        f"Ниша: {niche.get('category','')} / {niche.get('subcategory','')}.\n"
        f"Регион: {niche.get('region','')}.\n"
        f"Исключить (это сам клиент или уже учтённые): {exclude_str}.\n\n"
        f"Ниже — результаты поиска. Выбери из них РЕАЛЬНЫЕ компании-конкуренты, "
        f"которые оказывают услуги «{niche.get('category','')}» в регионе "
        f"«{niche.get('region','')}». НЕ включай агрегаторы, каталоги, справочники, "
        f"маркетплейсы, соцсети, статьи и новостные сайты. Верни только настоящие компании.\n\n"
        f"Результаты поиска:\n{lines}\n\n"
        f"Верни СТРОГО JSON-массив до {count} коротких названий компаний: "
        f'["Компания 1", "Компания 2", ...]. Только JSON.'
    )
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,
        )
        raw = (response.choices[0].message.content or "[]").strip()
        raw = raw.strip("```json").strip("```").strip()
        items = json.loads(raw)
        if not isinstance(items, list):
            return []
        excl_lower = {e.lower() for e in exclude}
        return [
            c.strip() for c in items
            if isinstance(c, str) and c.strip() and c.strip().lower() not in excl_lower
        ][:count]
    except Exception as exc:
        logger.warning("llm_extract_companies_error", error=str(exc))
        return []


async def _find_competitors_via_serp(
    niche: dict[str, Any],
    exclude: list[str],
    count: int = 5,
) -> list[str]:
    """Срочный фикс 3.1: конкуренты из реальной поисковой выдачи, не из памяти LLM."""
    category = niche.get("category", "")
    subcategory = niche.get("subcategory", "")
    region = niche.get("region", "")
    # Запрос вида «{category} {subcategory} {region}» — реальная локальная выдача.
    query = " ".join(p for p in [category, subcategory, region] if p).strip()
    if not query:
        return []

    results = await _xmlriver_search_results(query, region=region, num=20)
    # Отсеиваем агрегаторы/справочники/соцсети по домену.
    candidates = [r for r in results if r["domain"] and not _is_blacklisted_host(r["domain"])]
    if not candidates:
        return []

    confirmed = await _llm_extract_companies(candidates, niche, exclude, count)
    logger.info("competitors_from_serp", query=query, found=len(confirmed))
    return confirmed


async def find_competitors(
    niche: dict[str, Any],
    brand_name: str,
    count: int = 5,
    client_competitors: Optional[list[str]] = None,
) -> tuple[list[str], str]:
    """Подбирает конкурентов клиента.

    Возвращает (список, источник): "client" / "mixed" / "serp" / "llm_fallback".

    Приоритет (срочный фикс 3.1):
    1. Конкуренты от клиента (≥3) — самые точные.
    2. Реальная поисковая выдача через XMLRiver (НЕ из памяти модели) — для
       региональных/нишевых бизнесов это критично: модель не знает локальных игроков.
    3. LLM «из головы» — только если SERP ничего не дал. Помечаем low-confidence.
    """
    client_list = [c for c in (client_competitors or []) if c and c != brand_name][:count]

    # Приоритет 1/«mixed»: клиент указал ≥3.
    if len(client_list) >= 3:
        if len(client_list) >= count:
            logger.info("competitors_from_client_only", count=len(client_list), brand=brand_name)
            return client_list[:count], "client"
        # Добиваем из SERP, затем (если не хватило) из LLM.
        exclude = client_list + [brand_name]
        serp_extra = await _find_competitors_via_serp(niche, exclude=exclude, count=count)
        merged = _merge_dedupe(client_list, serp_extra, count)
        if len(merged) < count:
            llm_extra = await _find_competitors_via_llm(niche, brand_name, count)
            merged = _merge_dedupe(merged, llm_extra, count)
        logger.info("competitors_mixed", client=len(client_list), total=len(merged), brand=brand_name)
        return merged, "mixed"

    # Приоритет 2: реальный поиск (главный фикс релевантности).
    serp_competitors = await _find_competitors_via_serp(niche, exclude=[brand_name], count=count)
    if len(serp_competitors) >= 3:
        return serp_competitors[:count], "serp"

    # Приоритет 3 (fallback): LLM из головы — низкая достоверность, честно помечаем.
    llm_competitors = await _find_competitors_via_llm(niche, brand_name, count)
    # Если SERP что-то дал (1-2), смешиваем с LLM, чтобы не терять реальные имена.
    if serp_competitors:
        llm_competitors = _merge_dedupe(serp_competitors, llm_competitors, count)
    logger.info("competitors_llm_fallback", count=len(llm_competitors), brand=brand_name)
    return llm_competitors[:count], "llm_fallback"
