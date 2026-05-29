import asyncio
import json
import re
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
            model=settings.MODEL_EXTRACTION,
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


def _looks_like_url(s: str) -> bool:
    """Грубо: строка похожа на ссылку/домен (есть точка и доменная зона)."""
    s = s.strip().lower()
    if " " in s:
        return False
    return bool(re.match(r"^(https?://)?([a-z0-9\-]+\.)+[a-z]{2,}", s))


def _normalize_client_competitors(entries: Optional[list[str]], brand_name: str) -> list[str]:
    """Задача 5.2: клиент вводит ССЫЛКИ (или названия), по одной на строку.

    - URL → имя бренда из домена (buspartner.by → «Buspartner»).
    - Агрегаторы/соцсети/справочники — отбрасываем.
    - Сам сайт клиента и дубли — убираем. До 5 штук.
    """
    from app.utils.url_normalizer import extract_brand_from_url

    out: list[str] = []
    seen: set[str] = set()
    brand_l = (brand_name or "").strip().lower()
    for raw in entries or []:
        s = (raw or "").strip()
        if not s:
            continue
        if _looks_like_url(s):
            url = s if s.startswith("http") else f"http://{s}"
            host = _domain_of(url)
            if not host or _is_blacklisted_host(host):
                continue  # справочник/соцсеть — не конкурент
            name = extract_brand_from_url(url)
        else:
            name = s
        key = name.lower()
        if not name or key in seen or key == brand_l:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= 5:
            break
    return out


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
    btype = niche.get("business_type", "")
    btype_map = {
        "service": "оказывают УСЛУГИ того же рода (не продают софт и не товары)",
        "product": "продают ТОВАРЫ того же рода",
        "saas": "являются программным продуктом/платформой (SaaS) того же рода",
        "media": "являются СМИ/блогом/контент-площадкой того же рода",
    }
    btype_line = (
        f"Тип бизнеса клиента: {btype}. Бери ТОЛЬКО конкурентов, которые {btype_map[btype]}. "
        f"Например, для бухгалтерского аутсорса (услуга) НЕ бери 1С/Контур (это SaaS).\n"
        if btype in btype_map else ""
    )
    prompt = (
        f"Ниша: {niche.get('category','')} / {niche.get('subcategory','')}.\n"
        f"Регион: {niche.get('region','')}.\n"
        f"{btype_line}"
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
            model=settings.MODEL_EXTRACTION,
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
    """Итерация-3, Задача 1.2/4: конкуренты из РЕАЛЬНОЙ выдачи.

    Берём URL реальных сайтов (не агрегаторы) и извлекаем НАСТОЯЩЕЕ название
    компании С САМОГО САЙТА (schema.org/og:site_name/подвал) — НЕ из <title>
    (там SEO-фразы). Сайт не открылся / название не извлеклось → не конкурент.
    """
    from app.core.site_analyzer import fetch_org_name, looks_generic_name
    from app.utils.url_normalizer import extract_brand_from_url

    category = niche.get("category", "")
    subcategory = niche.get("subcategory", "")
    region = niche.get("region", "")
    query = " ".join(p for p in [category, subcategory, region] if p).strip()
    if not query:
        return []

    results = await _xmlriver_search_results(query, region=region, num=20)

    # Уникальные реальные домены (без агрегаторов/соцсетей), сохраняем порядок выдачи.
    seen_domains: set[str] = set()
    real_urls: list[str] = []
    for r in results:
        d = r.get("domain") or ""
        if not d or _is_blacklisted_host(d) or d in seen_domains:
            continue
        seen_domains.add(d)
        real_urls.append(r["url"])
    real_urls = real_urls[: max(count * 2, 8)]
    if not real_urls:
        logger.info("competitors_from_serp", query=query, real_domains=0, found=0)
        return []

    # Параллельно заходим на каждый сайт и достаём реальное название организации.
    names = await asyncio.gather(*[fetch_org_name(u) for u in real_urls], return_exceptions=True)

    excl_lower = {e.strip().lower() for e in exclude if e}
    out: list[str] = []
    seen_names: set[str] = set()
    for u, nm in zip(real_urls, names):
        name = nm if isinstance(nm, str) and nm.strip() else None
        if not name:
            # Сайт открылся, но название не извлеклось → берём бренд из домена
            # (buhvitebsk.by → «Buhvitebsk»). Не выдумка — это реальный домен.
            name = extract_brand_from_url(u) if isinstance(nm, str) or nm is None else None
        if not name or looks_generic_name(name):
            continue
        nl = name.lower()
        if nl in excl_lower or nl in seen_names:
            continue
        seen_names.add(nl)
        out.append(name)
        if len(out) >= count:
            break

    logger.info("competitors_from_serp", query=query, real_domains=len(real_urls), found=len(out))
    return out


async def extract_brands_from_ai_responses(
    raw_responses: dict,
    brand_name: str,
    niche: dict[str, Any],
    max_brands: int = 8,
) -> list[str]:
    """Итерация-3, Задача 1.1 (метод Profound): извлекаем РЕАЛЬНО упомянутые
    в ответах ИИ бренды-поставщики. Это языковая задача (извлечение сущностей
    из готового текста) — здесь LLM уместна.

    raw_responses: {model: {prompt: LLMResponse}}. Если ИИ не назвал конкретных
    компаний — вернём пустой список (честно: в нише нет ИИ-фаворитов).
    """
    texts: list[str] = []
    for _model, pmap in (raw_responses or {}).items():
        for _prompt, r in (pmap or {}).items():
            t = (getattr(r, "response_text", "") or "").strip()
            if t:
                texts.append(t)
    if not texts:
        return []

    # Группируем тексты в чанки (экономим вызовы), не более 6 чанков.
    chunks: list[str] = []
    cur = ""
    for t in texts:
        piece = t[:6000]
        if len(cur) + len(piece) > 6000 and cur:
            chunks.append(cur)
            cur = ""
        cur += "\n\n---\n\n" + piece
    if cur:
        chunks.append(cur)
    chunks = chunks[:6]

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL)
    category = niche.get("category", "")
    region = niche.get("region", "")
    sem = asyncio.Semaphore(4)

    async def _one(chunk: str) -> list[str]:
        prompt = (
            f"Ниже — ответы ИИ-ассистентов на запросы пользователей про «{category}» "
            f"в регионе «{region}».\n"
            f"Перечисли ТОЛЬКО названия КОНКРЕТНЫХ компаний/брендов, которые упомянуты "
            f"как поставщики этой услуги/товара.\n"
            f"НЕ включай: категории и родовые словосочетания («бухгалтерские услуги»), "
            f"города, госорганы, маркетплейсы/агрегаторы, а также сам бренд «{brand_name}».\n"
            f"Если конкретных компаний не названо — верни пустой массив [].\n\n"
            f"Ответы ИИ:\n{chunk}\n\n"
            f'Верни СТРОГО JSON-массив строк: ["Компания 1", "Компания 2"]. Только JSON.'
        )
        try:
            async with sem:
                resp = await client.chat.completions.create(
                    model=settings.MODEL_EXTRACTION,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=300,
                )
            raw = (resp.choices[0].message.content or "[]").strip()
            raw = raw.strip("```json").strip("```").strip()
            items = json.loads(raw)
            return [c.strip() for c in items if isinstance(c, str) and c.strip()] if isinstance(items, list) else []
        except Exception as exc:
            logger.warning("extract_brands_from_ai_error", error=str(exc))
            return []

    results = await asyncio.gather(*[_one(c) for c in chunks])

    from app.core.site_analyzer import looks_generic_name
    brand_l = (brand_name or "").strip().lower()
    counter: dict[str, int] = {}
    canonical: dict[str, str] = {}  # lower → оригинальное написание
    for lst in results:
        for name in lst:
            n = name.strip()
            nl = n.lower()
            if not n or nl == brand_l or looks_generic_name(n):
                continue
            counter[nl] = counter.get(nl, 0) + 1
            canonical.setdefault(nl, n)

    ranked = sorted(counter.items(), key=lambda kv: -kv[1])
    out = [canonical[nl] for nl, _ in ranked][:max_brands]
    logger.info("brands_from_ai_responses", found=len(out), candidates=list(counter.keys())[:10])
    return out


async def build_competitor_list(
    niche: dict[str, Any],
    brand_name: str,
    client_competitors: Optional[list[str]],
    raw_responses: dict,
    count: int = 5,
) -> tuple[list[str], str]:
    """Итерация-3, Задача 1.4: список конкурентов ТОЛЬКО из реальных данных.

    Приоритет: 1) ссылки клиента → 2) реально упомянутые в ответах ИИ (с
    проверкой реальным сайтом) → 3) реальная поисковая выдача. Никакого LLM
    «из головы». Если реальных <3 → source="sparse" (ниша свободна).
    """
    region = niche.get("region", "")
    client_list = _normalize_client_competitors(client_competitors, brand_name)[:count]
    if len(client_list) >= count:
        logger.info("competitors_from_client_only", count=len(client_list), brand=brand_name)
        return client_list[:count], "client"

    # Источник А — реально упомянутые ИИ бренды, верифицированные живым сайтом.
    ai_names = await extract_brands_from_ai_responses(raw_responses, brand_name, niche)
    ai_verified: list[str] = []
    if ai_names:
        urls = await asyncio.gather(
            *[find_competitor_url(n, region) for n in ai_names], return_exceptions=True
        )
        for n, u in zip(ai_names, urls):
            if isinstance(u, str) and u:
                ai_verified.append(n)
        logger.info("competitors_from_ai_verified", candidates=len(ai_names), verified=len(ai_verified))

    # Источник Б — реальная поисковая выдача (без уже учтённых).
    exclude = [brand_name] + client_list + ai_verified
    serp = await _find_competitors_via_serp(niche, exclude=exclude, count=count)

    # Слияние с приоритетом: клиент → ИИ-верифицированные → выдача.
    merged = _merge_dedupe(client_list, ai_verified, count)
    merged = _merge_dedupe(merged, serp, count)

    if len(merged) >= 3:
        source = "client" if (client_list and not ai_verified and not serp) else "verified"
        return merged[:count], source

    # Реальных конкурентов <3 → честный сигнал «ниша свободна».
    logger.info("competitors_sparse", count=len(merged), brand=brand_name)
    return merged[:count], "sparse"


async def find_competitors(
    niche: dict[str, Any],
    brand_name: str,
    count: int = 5,
    client_competitors: Optional[list[str]] = None,
) -> tuple[list[str], str]:
    """Подбирает конкурентов клиента.

    Возвращает (список, источник): "client" / "mixed" / "serp" / "sparse".

    Приоритет (Итерация-3, Задача 1.4 — разворот на реальные данные):
    1. Конкуренты от клиента (≥3) — самые точные.
    2. Реальная поисковая выдача через XMLRiver (НЕ из памяти модели).
    3. Если реальных <3 — честно «sparse» (ниша свободна). НИКОГДА не выдумываем
       конкурентов через LLM «из головы»: лучше «в нише мало игроков» (правда),
       чем правдоподобная ложь, которая убивает доверие к отчёту.
    """
    # Задача 5.2: клиент вводит ссылки/названия — нормализуем (URL → имя, фильтр агрегаторов).
    client_list = _normalize_client_competitors(client_competitors, brand_name)[:count]

    # Приоритет 1/«mixed»: клиент указал ≥3.
    if len(client_list) >= 3:
        if len(client_list) >= count:
            logger.info("competitors_from_client_only", count=len(client_list), brand=brand_name)
            return client_list[:count], "client"
        # Добиваем ТОЛЬКО реальной выдачей (никакого LLM-добивания).
        exclude = client_list + [brand_name]
        serp_extra = await _find_competitors_via_serp(niche, exclude=exclude, count=count)
        merged = _merge_dedupe(client_list, serp_extra, count)
        logger.info("competitors_mixed", client=len(client_list), total=len(merged), brand=brand_name)
        return merged, "mixed"

    # Приоритет 2: реальный поиск (главный источник).
    serp_competitors = await _find_competitors_via_serp(niche, exclude=[brand_name], count=count)
    if len(serp_competitors) >= 3:
        return serp_competitors[:count], "serp"

    # Приоритет 3: реальных конкурентов <3 → честный сигнал «ниша свободна».
    # Возвращаем что нашли (0-2 реальных), отчёт уйдёт в ветку «ниша свободна».
    logger.info("competitors_sparse", count=len(serp_competitors), brand=brand_name)
    return serp_competitors[:count], "sparse"
