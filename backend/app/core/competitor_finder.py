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
    # Соцсети и мессенджеры
    "vk.com", "instagram.com", "facebook.com", "ok.ru", "youtube.com",
    "t.me", "twitter.com", "x.com", "tiktok.com", "linkedin.com",
    # Маркетплейсы РФ
    "ozon.ru", "wildberries.ru", "wb.ru", "avito.ru", "youla.ru",
    "drom.ru", "auto.ru", "cian.ru", "yandex.market", "market.yandex.ru",
    "sbermegamarket.ru", "megamarket.ru", "aliexpress.ru", "aliexpress.com",
    "lamoda.ru", "citilink.ru", "mvideo.ru", "eldorado.ru", "dns-shop.ru",
    # Маркетплейсы/агрегаторы РБ (Итерация-3: Куфар не должен быть «конкурентом»)
    "21vek.by", "kufar.by", "av.by", "hata.by", "deal.by", "relax.by",
    "onliner.by", "praca.by", "rabota.by", "salonbel.by", "1prof.by",
    "oz.by", "5element.by", "electrosila.by",
    # Недвижимость (Задача 1, кейс akbtrade.by: gohome.by попадала в Блок А)
    "gohome.by", "n1.by", "realt.by", "domovita.by", "realty.yandex.ru",
    "domclick.ru", "n1.ru", "m2.ru",
    # Телеком/операторы — НЕ конкуренты обычным интернет-магазинам
    "a1.by", "mts.by", "mts.ru", "life.com.by", "lifeforyou.by",
    "belka.by", "velcom.by", "beltelecom.by", "byfly.by",
    "megafon.ru", "tele2.ru", "beeline.ru", "rostelecom.ru",
    # Авто-порталы и автогазеты (не магазины аккумуляторов/запчастей)
    "abw.by", "av.by", "auto.by", "autobild.by", "carmania.by",
    "drive2.ru", "drive2.by", "kolesa.kz",
    # Справочники/карты
    "2gis.ru", "2gis.by", "yandex.ru", "ya.ru", "google.com", "google.ru",
    "yandex.by", "google.by", "maps.google.com",
    "spr.by", "flamp.ru", "flamp.by", "rejting.by",
    "tripadvisor.ru", "tripadvisor.com", "booking.com", "ostrovok.ru",
    # Энциклопедии/новости
    "wikipedia.org", "ru.wikipedia.org", "be.wikipedia.org",
    "tut.by", "onliner.by", "sb.by", "belta.by", "rbc.ru", "lenta.ru",
    # Отельные / туристические агрегаторы — каналы продаж, НЕ конкуренты
    # базам отдыха/гостиницам/агроусадьбам (Booking-подобные).
    "101hotels.com", "101hotels.ru", "hotels.com", "ostrovok.ru",
    "sutochno.ru", "tvil.ru", "bronevik.com", "otello.ru",
    "agoda.com", "airbnb.com", "airbnb.ru", "expedia.com",
    "hotellook.ru", "hotellook.com", "trivago.ru", "trivago.com",
    "tury.ru", "vse-otely.ru", "tonkosti.ru", "oktogo.ru",
    "suntime.ru", "level.travel", "travelata.ru", "onlinetours.ru",
    "tripster.ru", "sputnik8.com", "bigrussia.org",
    # Бизнес-реестры/каталоги юрлиц (не провайдеры услуги)
    "checko.ru", "rusprofile.ru", "list-org.com", "sbis.ru", "kontur.ru",
    "nalog.ru", "nalog.gov.ru", "egrul.nalog.ru", "egr.gov.by",
    "spravka.ru", "yell.ru", "zoon.ru", "zoon.by",
    # Региональные бизнес-каталоги
    "vitebsk.biz", "minsk.biz", "by.biz", "byinform.com",
    # Госорганы и образование (не провайдеры коммерческих услуг)
    "gov.by", "gov.ru", "gosuslugi.ru", "mos.ru",
    "edu.by", "edu.ru", "mail.ru", "rambler.ru",
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
                    # groupby БЕЗ loc вызывает error code 104 «Неверный параметр loc!»
                    # (доказано прогоном на 'аккумуляторы минск'). Без groupby
                    # XMLRiver возвращает топ результатов сам.
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


_LEGAL_FORMS = {
    "ооо", "одо", "уп", "чуп", "чтуп",
    "ип", "оао", "зао", "ао", "пао",
}


def _starts_with_legal_form(name: str) -> bool:
    """True если name начинается с юр.формы («ООО Стиген», «ИП Гринь»).

    Для интернет-магазинов юр.имя ничего не говорит клиенту — домен
    (stigen.by) узнаваем сразу, а «ООО Стиген» абстрактно. Используем
    это как сигнал «предпочтительнее домен».
    """
    if not name:
        return False
    first = (name.split() or [""])[0].strip(".,«»\"'-").lower()
    return first in _LEGAL_FORMS


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


def _client_country(region: str) -> str:
    """Страна клиента из строки region («Витебск, Беларусь» → «Беларусь»)."""
    r = (region or "").lower()
    if "беларус" in r or r.strip() in ("рб", "by") or r.endswith(", рб"):
        return "Беларусь"
    if "росси" in r or r.strip() in ("рф", "ru") or r.endswith(", рф"):
        return "Россия"
    if "казахст" in r or "kz" in r:
        return "Казахстан"
    if "украин" in r or "ua" in r:
        return "Украина"
    return ""


async def _xmlriver_google_results(query: str, region: str = "Россия", num: int = 20) -> list[dict]:
    """Google-выдача через XMLRiver (`/search_google/xml`). Итерация-3: для
    Беларуси Google даёт реальные витебские фирмы, Яндекс беднее. Если эндпоинт
    не отвечает / параметры не приняты — возвращает [], не ломает Yandex-путь.
    """
    if not settings.XMLRIVER_USER or not settings.XMLRIVER_KEY:
        return []
    # Для Google нужен ИХ country code (2643=РФ, 2112=РБ), не Yandex lr.
    is_by = "беларус" in region.lower() or "by" in region.lower()
    country = (
        settings.XMLRIVER_GOOGLE_COUNTRY_BY if is_by else settings.XMLRIVER_GOOGLE_COUNTRY_RU
    )
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            # Правильный Google эндпоинт XMLRiver — /search/xml (проверено
            # рабочим запросом пользователя). /search_google/xml возвращал
            # пустоту с тем же ключом.
            response = await client.get(
                "https://xmlriver.com/search/xml",
                params={
                    "user": settings.XMLRIVER_USER,
                    "key": settings.XMLRIVER_KEY,
                    "query": query,
                    "country": country,
                    # groupby убран — он требует loc и без него XMLRiver кидает
                    # error 104. По умолчанию вернётся топ-10 результатов.
                },
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("serp_google_error", query=query, error=str(exc))
        return []

    out: list[dict] = []
    try:
        root = ET.fromstring(response.text)
        for doc in root.findall(".//doc"):
            url_el = doc.find("url")
            title_el = doc.find("title")
            url = (url_el.text or "").strip() if url_el is not None else ""
            title = (title_el.text or "").strip() if title_el is not None else ""
            if url:
                out.append({"title": title, "url": url, "domain": _domain_of(url), "source": "google"})
    except ET.ParseError as exc:
        logger.warning("serp_google_parse_error", query=query, error=str(exc))
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
                # Правильный Yandex эндпоинт: /search_yandex/xml. Раньше шли на
                # /search/xml — это Google по их документации, мы случайно
                # получали Yandex-подобный ответ только потому что без country
                # Google отдаёт пустоту, а парсер искал <doc>. См. документацию
                # XMLRiver, апрель 2024+.
                "https://xmlriver.com/search_yandex/xml",
                params={
                    "user": settings.XMLRIVER_USER,
                    "key": settings.XMLRIVER_KEY,
                    "query": query,
                    "lr": lr,
                    # groupby убран — он требует loc и без него XMLRiver кидает
                    # error 104. По умолчанию вернётся топ-10 результатов.
                },
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning("serp_yandex_error", query=query, error=str(exc))
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
            out.append({"title": title, "url": url, "domain": _domain_of(url), "source": "yandex"})
    except ET.ParseError as exc:
        logger.warning("serp_yandex_parse_error", query=query, error=str(exc))
    return out


async def _xmlriver_search_combined(query: str, region: str = "Россия", num: int = 20) -> list[dict]:
    """Итерация-3: Google как основной источник (для РБ даёт больше реальных
    фирм) + Yandex как fallback. Параллельно опрашиваем оба, объединяем,
    дедупим по URL. Google идёт первым в порядке (более релевантный).
    """
    g, y = await asyncio.gather(
        _xmlriver_google_results(query, region, num),
        _xmlriver_search_results(query, region, num),
        return_exceptions=True,
    )
    out: list[dict] = []
    seen: set[str] = set()
    for src in (g, y):
        if not isinstance(src, list):
            continue
        for r in src:
            u = r.get("url") or ""
            if not u or u in seen:
                continue
            seen.add(u)
            out.append(r)
    logger.info(
        "serp_combined",
        query=query,
        google=len(g) if isinstance(g, list) else 0,
        yandex=len(y) if isinstance(y, list) else 0,
        merged=len(out),
    )
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
    from app.core.site_analyzer import (
        fetch_site_summary,
        looks_generic_name,
        is_placeholder_name,
        looks_like_slogan,
        country_from_site,
    )

    # SERP-запрос = subcategory (если есть) или category + город.
    # ОТКАТ «первого слова» (Задача 1, akbtrade.by-кейс): для subcategory
    # «автомобильные аккумуляторы» первое слово = «автомобильные» давало
    # запрос «автомобильные минск» → мусор (телеком, недвижимость).
    # После фикса User-Agent заголовков XMLRiver принимает и длинные фразы;
    # «автомобильные аккумуляторы минск» возвращает реальные магазины АКБ.
    # Стоп-слова из subcategory чистим, чтобы не было «и/или/для» в запросе.
    def _clean_phrase(phrase: str) -> str:
        STOP = {"и", "или", "для", "под", "при", "на", "в", "с", "по", "об", "от", "до"}
        words = []
        for w in (phrase or "").split():
            wn = w.strip("«»\"'.,()-—:;").lower()
            if wn and wn not in STOP:
                words.append(w)
        return " ".join(words)

    def _first_keyword(phrase: str) -> str:
        """Первое значимое слово (≥5 букв) — для SERP-fallback при пустом
        результате по полной фразе. XMLRiver на длинных многословных запросах
        часто отдаёт 0 (например, «Аккумуляторы аксессуары Минск» → 0
        доменов, а «Аккумуляторы Минск» → 9). Это страховка."""
        STOP = {"и", "или", "для", "под", "при", "на", "в", "с", "по",
                "об", "от", "до"}
        for w in (phrase or "").split():
            wn = w.strip("«»\"'.,()-—:;").lower()
            if wn and wn not in STOP and len(wn) >= 5:
                return w
        return (phrase or "").strip()

    cat = niche.get("category", "") or ""
    sub = niche.get("subcategory", "") or ""
    primary = _clean_phrase(sub) or _clean_phrase(cat) or cat.strip()
    region = niche.get("region", "")
    city = _city_from_region(region) or region
    query = " ".join(p for p in [primary, city] if p).strip()
    if not query:
        return []

    # Итерация-3: Google как основной источник + Yandex как fallback.
    results = await _xmlriver_search_combined(query, region=region, num=20)
    # ФИКС 31.05: XMLRiver SERP флуктуирует на длинных фразах. Если
    # «Аккумуляторы аксессуары Минск» вернуло 0, повторяем запрос
    # сокращённым «Аккумуляторы Минск» (первое значимое слово subcategory).
    # Это страховка, чтобы Block A не падал из-за случайной волатильности
    # XMLRiver. На стабильных запросах второго захода не будет.
    if not results:
        short_primary = _first_keyword(sub) or _first_keyword(cat)
        if short_primary and short_primary.lower() != primary.lower():
            short_query = " ".join(p for p in [short_primary, city] if p).strip()
            if short_query and short_query.lower() != query.lower():
                logger.info(
                    "serp_fallback_short_query",
                    primary_query=query,
                    short_query=short_query,
                )
                results = await _xmlriver_search_combined(
                    short_query, region=region, num=20
                )
                if results:
                    query = short_query  # для лога ниже

    # Уникальные реальные домены (без агрегаторов/соцсетей), сохраняем порядок.
    seen_domains: set[str] = set()
    real_urls: list[str] = []
    for r in results:
        d = r.get("domain") or ""
        if not d or _is_blacklisted_host(d) or d in seen_domains:
            continue
        seen_domains.add(d)
        real_urls.append(r["url"])
    real_urls = real_urls[: max(count * 4, 15)]  # запас на отсев по категории/региону
    if not real_urls:
        logger.info("competitors_from_serp", query=query, real_domains=0, found=0)
        return []

    # Параллельно заходим на каждый сайт: имя + кусок текста для проверок.
    summaries = await asyncio.gather(
        *[fetch_site_summary(u) for u in real_urls], return_exceptions=True
    )
    keywords = _category_keywords(niche)
    client_country = _client_country(region)

    excl_lower = {e.strip().lower() for e in exclude if e}
    out: list[str] = []
    seen_names: set[str] = set()
    rej_off_topic = 0
    rej_wrong_country = 0
    rej_no_real_site = 0
    rej_generic = 0
    for u, summ in zip(real_urls, summaries):
        if not isinstance(summ, dict):
            continue
        text = summ.get("text") or ""
        org_name = (summ.get("org_name") or "").strip()

        # Конъюнктивный confidence-фильтр. Сначала проверяем, что САЙТ нам подходит
        # (регион + категория), и ТОЛЬКО ПОТОМ решаем по имени. Если сайт реальный
        # и наш, но имя метаданных мусорное — оставляем кандидата с доменом-меткой,
        # а не теряем реального конкурента (buhvitebsk.by — реальная фирма).

        # 1. Регион сайта = регион клиента (TLD + сигналы текста).
        if client_country:
            site_country = country_from_site(u, text)
            if site_country and site_country != client_country:
                rej_wrong_country += 1
                continue
        # 2. Категория сайта = категория клиента (стемы повторяются ≥2 раз).
        if not _site_matches_category(text, keywords):
            rej_off_topic += 1
            continue

        # 3. Имя. Приоритет: реальное название с сайта.
        # Если оно generic, placeholder, слоган ИЛИ начинается с юр.формы
        # («ООО Стиген», «ИП Гринь», «Отдых в гармонии с природой!») —
        # берём домен. Для интернет-магазинов домен (stigen.by) узнаваемее
        # юр.имени — клиент сразу видит, какой это магазин.
        domain_label = (_domain_of(u) or "").lower()
        if (
            org_name
            and not looks_generic_name(org_name)
            and not is_placeholder_name(org_name)
            and not looks_like_slogan(org_name)
            and not _starts_with_legal_form(org_name)
        ):
            name = org_name
        else:
            if org_name and _starts_with_legal_form(org_name):
                pass  # это нормальный сигнал «лучше показать домен», не мусор
            elif org_name:
                rej_generic += 1
            name = domain_label
        if not name:
            rej_no_real_site += 1
            continue

        nl = name.lower()
        if nl in excl_lower or nl in seen_names:
            continue
        seen_names.add(nl)
        out.append(name)
        if len(out) >= count:
            break

    logger.info(
        "competitors_from_serp",
        query=query,
        real_domains=len(real_urls),
        found=len(out),
        rej_no_real_site=rej_no_real_site,
        rej_generic=rej_generic,
        rej_wrong_country=rej_wrong_country,
        rej_off_topic=rej_off_topic,
        keywords=keywords,
        client_country=client_country,
    )
    return out


def _category_keywords(niche: dict[str, Any]) -> list[str]:
    """Итерация-3, Задача 4 (+v2): отличительные стемы ниши — для проверки,
    что сайт кандидата реально про эту услугу/товар. Берём стемы И из category,
    И из subcategory — для «Автоаксессуары / Аккумуляторы для транспорта»
    получаем ['автоак', 'аккуму', 'транс'], то есть сайт реального магазина
    аккумуляторов теперь пройдёт по стему «аккуму», даже если category общая.
    """
    from app.core.site_analyzer import _GENERIC_WORDS
    cat = (niche.get("category") or "").strip()
    sub = (niche.get("subcategory") or "").strip()
    # ИЗ ОБЕИХ ЧАСТЕЙ — иначе магазин аккумуляторов не проходит фильтр
    # по category «автоаксессуары» (стем «автоак»), хотя subcategory чётко
    # сужает до «аккумуляторы».
    raw = " ".join([cat, sub]).lower()
    tokens = [t.strip("«»\"'.,()-—:;") for t in raw.split() if t]
    distinctive = [t for t in tokens if t and t not in _GENERIC_WORDS and len(t) >= 5]
    # стем = первые 6 символов (грубо, но для русского работает).
    return list({t[:6] for t in distinctive})


def _site_matches_category(text: str, keywords: list[str], min_total: int = 2) -> bool:
    """True, если сайт реально про эту категорию.

    Итерация-3: одного вхождения мало — «Юрист для людей» иногда упоминает
    «бухгалтерские услуги» в списке смежных услуг, но это не бухгалтерская
    фирма. Требуем СУММУ вхождений всех стемов категории ≥ min_total —
    реальный профильный сайт повторяет ключевые слова много раз, случайное
    упоминание это не пройдёт.
    """
    if not keywords:
        return True
    if not text:
        return False
    t = text.lower()
    total = sum(t.count(k) for k in keywords)
    return total >= min_total


def _city_from_region(region: str) -> str:
    """«Витебск, Беларусь» → «Витебск». Берём первую часть до запятой."""
    if not region:
        return ""
    return region.split(",")[0].strip()


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
            f"в регионе «{region}».\n\n"
            f"Перечисли ТОЛЬКО названия конкретных компаний/брендов, которые в этих "
            f"ответах названы как РЕАЛЬНЫЕ ПРОВАЙДЕРЫ услуги «{category}» в «{region}».\n\n"
            f"СТРОГО ИСКЛЮЧИ:\n"
            f"- родовые словосочетания и категории («бухгалтерские услуги», «аудит»);\n"
            f"- города, регионы, госорганы (Госуслуги, Налоговая, ПФР, ФСС,\n"
            f"  министерства, ведомства — это инфраструктура, не конкуренты);\n"
            f"- маркетплейсы и агрегаторы (Wildberries, Ozon, 21vek, Avito,\n"
            f"  Kufar — это каналы продаж, не конкуренты);\n"
            f"- крупные классифайды/справочники (Onliner, 2GIS, Zoon, Yell);\n"
            f"- сущности, упомянутые мимоходом (примеры клиентов, контрагентов) —\n"
            f"  если компания упомянута НЕ как поставщик «{category}», а в другом контексте,\n"
            f"  её сюда НЕ включай;\n"
            f"- сам бренд «{brand_name}».\n"
            f"Если в ответах нет конкретных провайдеров «{category}» — верни [].\n\n"
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


async def _find_competitors_from_ai_citations(
    niche: dict[str, Any],
    brand_name: str,
    ai_citations: dict,
    exclude: list[str],
    count: int = 5,
) -> list[str]:
    """ТЗ catcore-blok-a-iz-realnoy-vydachi: Блок А из РЕАЛЬНОЙ выдачи —
    citations <item> из Google AI Overview. Это URL, на которые AI Overview
    реально ссылается в ответе — детерминированные реальные сайты, не
    галлюцинации генеративных моделей.

    ai_citations = {model_name: {prompt: [url1, url2, ...]}}.
    Берём все URL, фильтруем blacklist + регион (СТРОГО) + категория (≥2).
    Имя — site_name → org_name (без юр.формы и слогана) → домен.
    """
    from app.core.site_analyzer import (
        fetch_site_summary,
        looks_generic_name,
        is_placeholder_name,
        looks_like_slogan,
        country_from_site,
    )

    region = niche.get("region", "")
    client_country = _client_country(region)
    excl_lower = {e.strip().lower() for e in (exclude or []) if e}
    brand_lc = (brand_name or "").lower()

    # 1) Собираем уникальные URL из всех моделей и промптов.
    seen_domains: set[str] = set()
    urls: list[str] = []
    for _model, pmap in (ai_citations or {}).items():
        for _prompt, lst in (pmap or {}).items():
            for u in lst or []:
                if not isinstance(u, str) or not u.startswith(("http://", "https://")):
                    continue
                d = _domain_of(u)
                if not d or _is_blacklisted_host(d) or d in seen_domains:
                    continue
                seen_domains.add(d)
                urls.append(u)
    urls = urls[: max(count * 4, 12)]
    if not urls:
        logger.info("competitors_from_citations_empty", brand=brand_name)
        return []

    # 2) Параллельно тянем краткие summary каждого сайта.
    summaries = await asyncio.gather(
        *[fetch_site_summary(u) for u in urls], return_exceptions=True
    )
    keywords = _category_keywords(niche)

    def _ok_name(n: str) -> bool:
        return (
            bool(n)
            and not looks_generic_name(n)
            and not is_placeholder_name(n)
            and not looks_like_slogan(n)
            and not _starts_with_legal_form(n)
        )

    out: list[str] = []
    seen: set[str] = set()
    rej_off_topic = rej_wrong_country = rej_generic = 0
    for u, summ in zip(urls, summaries):
        if not isinstance(summ, dict):
            continue
        text = summ.get("text") or ""
        site_name = (summ.get("org_name") or "").strip()

        # СТРОГИЙ регион: если site_country известен и не совпадает — выкинуть;
        # если site_country НЕ определён — тоже выкинуть (для Block A нужно
        # подтверждение региона, иначе .com сайты пробираются как «локальные»).
        if client_country:
            site_country = country_from_site(u, text)
            if not site_country or site_country != client_country:
                rej_wrong_country += 1
                continue
        # Категория ≥2 вхождений стемов (как и SERP-органика Блока А).
        if not _site_matches_category(text, keywords, min_total=2):
            rej_off_topic += 1
            continue

        # Имя: site_name → orig_name (из meta-title — нет ai-name) → домен.
        domain_label = (_domain_of(u) or "").lower()
        if _ok_name(site_name):
            name = site_name
        else:
            if site_name and not _ok_name(site_name):
                rej_generic += 1
            name = domain_label
        if not name:
            continue
        nl = name.lower()
        if nl in seen or nl in excl_lower or nl == brand_lc:
            continue
        seen.add(nl)
        out.append(name)
        if len(out) >= count:
            break

    logger.info(
        "competitors_from_citations",
        citation_urls=len(urls),
        accepted=len(out),
        rej_off_topic=rej_off_topic,
        rej_wrong_country=rej_wrong_country,
        rej_generic=rej_generic,
    )
    return out


async def _find_competitors_from_ai_responses(
    niche: dict[str, Any],
    brand_name: str,
    raw_responses: dict,
    exclude: list[str],
    count: int = 5,
) -> list[str]:
    """Задача 1.1 ТЗ: извлекаем РЕГИОНАЛЬНЫХ нишевых конкурентов из ответов ИИ.

    Отличия от extract_ai_mentioned_in_niche (Блок Б):
    - регион СТРОГО (как в Блоке А SERP) — Блок А обещает прямых региональных
      конкурентов, не федералов;
    - категория-фильтр СТРОГИЙ (min_total=2), как в Блоке А SERP;
    - blacklist агрегаторов/нелокальных доменов применяется.

    Источник: текст ответов всех моделей (включая Yandex Neuro / Google AI
    Overview). LLM-извлечение брендов через extract_brands_from_ai_responses —
    разрешённое использование LLM (анализ готового текста, не генерация).

    Не дёргаем citations отдельно: их URL уже всплывают в bra LLM-extraction
    через имена в тексте, далее find_competitor_url догоняет нужный сайт.
    """
    from app.core.site_analyzer import (
        fetch_site_summary,
        looks_generic_name,
        is_placeholder_name,
        looks_like_slogan,
        country_from_site,
    )

    region = niche.get("region", "")
    client_country = _client_country(region)
    ai_names = await extract_brands_from_ai_responses(raw_responses, brand_name, niche)
    excl_lower = {e.strip().lower() for e in (exclude or []) if e}
    brand_lc = (brand_name or "").lower()

    # Выкидываем плейсхолдеры, generic-имена («21 Век», «Электроника»),
    # дубли с exclude — ДО SERP-поиска. Если LLM назвала родовую категорию
    # вместо бренда, по ней find_competitor_url находит сайт-агрегатор,
    # name=домен после fallback пропускает мусор в Block A.
    ai_names = [
        n for n in ai_names
        if n
        and not is_placeholder_name(n)
        and not looks_generic_name(n)
        and not looks_like_slogan(n)
        and n.lower() not in excl_lower
        and n.lower() != brand_lc
    ]
    if not ai_names:
        logger.info("competitors_from_ai_responses_empty", brand=brand_name)
        return []

    # Каждое имя → SERP-поиск URL. find_competitor_url применяет blacklist.
    urls = await asyncio.gather(
        *[find_competitor_url(n, region) for n in ai_names], return_exceptions=True
    )
    valid_pairs = [(n, u) for n, u in zip(ai_names, urls) if isinstance(u, str) and u]
    if not valid_pairs:
        logger.info("competitors_from_ai_responses_no_urls", brand=brand_name, candidates=len(ai_names))
        return []

    summaries = await asyncio.gather(
        *[fetch_site_summary(u) for _, u in valid_pairs], return_exceptions=True
    )
    keywords = _category_keywords(niche)

    out: list[str] = []
    seen: set[str] = set()
    rej_off_topic = rej_wrong_country = rej_generic = 0
    for (orig_name, u), summ in zip(valid_pairs, summaries):
        if not isinstance(summ, dict):
            continue
        text = summ.get("text") or ""
        site_name = (summ.get("org_name") or "").strip()

        # 1. Регион сайта = регион клиента (СТРОГО, это Блок А).
        if client_country:
            site_country = country_from_site(u, text)
            if site_country and site_country != client_country:
                rej_wrong_country += 1
                continue
        # 2. Категория — строго ≥2 повторений стемов (как в Блоке А SERP).
        if not _site_matches_category(text, keywords, min_total=2):
            rej_off_topic += 1
            continue
        # 3. Имя: site_name (без юр.формы) → orig_name (без юр.формы) → домен.
        # Юр.форма («ООО Стиген», «ИП Гринь») = «лучше показать домен»,
        # клиенту он узнаваемее.
        def _ok(n: str) -> bool:
            return (
                bool(n)
                and not looks_generic_name(n)
                and not is_placeholder_name(n)
                and not _starts_with_legal_form(n)
            )
        domain_label = (_domain_of(u) or "").lower()
        if _ok(site_name):
            name = site_name
        elif _ok(orig_name):
            name = orig_name
        else:
            name = domain_label
        if not name:
            rej_generic += 1
            continue
        nl = name.lower()
        if nl in seen or nl in excl_lower or nl == brand_lc:
            continue
        seen.add(nl)
        out.append(name)
        if len(out) >= count:
            break

    logger.info(
        "competitors_from_ai_responses",
        candidates=len(ai_names),
        with_url=len(valid_pairs),
        accepted=len(out),
        rej_off_topic=rej_off_topic,
        rej_wrong_country=rej_wrong_country,
        rej_generic=rej_generic,
    )
    return out


async def build_competitor_list(
    niche: dict[str, Any],
    brand_name: str,
    client_competitors: Optional[list[str]],
    count: int = 5,
    ai_citations: Optional[dict] = None,
) -> tuple[list[str], str, dict[str, str]]:
    """Блок А — каскад из РЕАЛЬНОЙ выдачи (ТЗ catcore-blok-a-iz-realnoy-vydachi):

        1. КЛИЕНТСКИЕ (форма)         → если ≥ count, ТОЛЬКО они, source="client"
        2. CITATIONS <item> Google AI Overview → реальные URL из AI-ответа
                                       (детерминированные сайты, не галлюцинации)
        3. ОРГАНИКА (SERP)            → дополняем до count
        4. SPARSE                     → если всё < 3, "sparse"

    LLM-извлечение брендов из текстов ответов моделей (extract_brands_from_ai_
    responses) для Блока А БОЛЬШЕ НЕ ИСПОЛЬЗУЕТСЯ — слоганы и агрегаторы
    прорывались. Эта функция теперь питает только Блок Б.

    Возвращает (names, overall_source, per_name_source_map).
    Источники в map: "client" / "ai_overview" / "serp_direct".
    """
    client_list = _normalize_client_competitors(client_competitors, brand_name)[:count]
    sources_map: dict[str, str] = {n.lower(): "client" for n in client_list}

    if len(client_list) >= count:
        logger.info("competitors_from_client_only", count=len(client_list), brand=brand_name)
        return (
            client_list[:count],
            "client",
            {n: "client" for n in client_list[:count]},
        )

    # === Этап 2: AI Overview citations (реальные URL из <item>) ===
    ai_names: list[str] = []
    if ai_citations:
        try:
            ai_names = await _find_competitors_from_ai_citations(
                niche,
                brand_name=brand_name,
                ai_citations=ai_citations,
                exclude=[brand_name] + client_list,
                count=count - len(client_list),
            )
        except Exception as exc:
            logger.warning("ai_citations_block_a_failed", error=str(exc))
            ai_names = []
        for n in ai_names:
            sources_map.setdefault(n.lower(), "ai_overview")

    after_ai = _merge_dedupe(client_list, ai_names, count)

    # === Этап 3: SERP-органика как дополнение ===
    serp_names: list[str] = []
    if len(after_ai) < count:
        exclude = [brand_name] + after_ai
        try:
            serp_names = await _find_competitors_via_serp(
                niche, exclude=exclude, count=count - len(after_ai)
            )
        except Exception as exc:
            logger.warning("serp_block_a_failed", error=str(exc))
            serp_names = []
        for n in serp_names:
            sources_map.setdefault(n.lower(), "serp_direct")

    merged = _merge_dedupe(after_ai, serp_names, count)

    # Источник для лога/отчёта
    if client_list and ai_names and not serp_names:
        source = "client+ai_overview"
    elif ai_names and not serp_names:
        source = "ai_overview"
    elif ai_names and serp_names:
        source = "ai_overview+serp"
    elif client_list and not ai_names and not serp_names:
        source = "client"
    elif serp_names and not ai_names:
        source = "verified"  # legacy-имя для «только SERP»
    else:
        source = "sparse"

    if len(merged) < 3:
        source = "sparse"
        logger.info("competitors_sparse", count=len(merged), brand=brand_name)

    per_name = {n: sources_map.get(n.lower(), "serp_direct") for n in merged[:count]}
    return merged[:count], source, per_name


async def extract_ai_mentioned_in_niche(
    raw_responses: dict,
    niche: dict[str, Any],
    brand_name: str,
    existing_block_a: list[str],
    count: int = 5,
) -> tuple[list[str], dict[str, dict]]:
    """Блок Б отчёта: кого ИИ реально называет В ВАШЕЙ НИШЕ.

    По ТЗ catcore-konkurenty-iz-ai-vydachi (Задача 3): для не-локальных
    игроков добавляем метку «федеральный игрок, не локальный конкурент»,
    чтобы юзер не считал «1С» прямым конкурентом витебской бухгалтерии.

    Регион сайта НЕ проверяем строго (это ровно та секция, где ИИ называет
    федералов), но РАСПОЗНАЁМ его и помечаем — `is_federal=True`, когда
    страна сайта не совпадает с регионом клиента (или сайт явно межстрановой).

    Возвращает кортеж:
      - list[str] — имена (до count) в порядке добавления
      - dict[str_lower, dict] — meta по каждому имени:
            {"is_federal": bool, "site_country": str}

    Используется report-builder'ом для Блока Б.
    """
    from app.core.site_analyzer import (
        fetch_site_summary,
        looks_generic_name,
        is_placeholder_name,
        looks_like_slogan,
        country_from_site,
    )

    region = niche.get("region", "")
    ai_names = await extract_brands_from_ai_responses(raw_responses, brand_name, niche)
    if not ai_names:
        logger.info("ai_mentioned_in_niche_empty", brand=brand_name)
        return []

    # Плейсхолдеры, generic, slogan и совпадения с Блоком А — выкидываем
    # до похода в SERP. ТЗ catcore-blok-a-iz-realnoy-vydachi:
    # «Отдых в гармонии с природой!» не должно быть в Блоке Б.
    block_a_lc = {n.lower() for n in (existing_block_a or [])}
    brand_lc = (brand_name or "").lower()
    ai_names = [
        n for n in ai_names
        if not is_placeholder_name(n)
        and not looks_generic_name(n)
        and not looks_like_slogan(n)
        and n.lower() not in block_a_lc
        and n.lower() != brand_lc
    ]
    if not ai_names:
        return [], {}

    urls = await asyncio.gather(
        *[find_competitor_url(n, region) for n in ai_names], return_exceptions=True
    )
    keywords = _category_keywords(niche)
    client_country = _client_country(region)
    valid_pairs = [(n, u) for n, u in zip(ai_names, urls) if isinstance(u, str) and u]
    summaries = await asyncio.gather(
        *[fetch_site_summary(u) for _, u in valid_pairs], return_exceptions=True
    )

    out: list[str] = []
    meta: dict[str, dict] = {}
    seen: set[str] = set()
    rej_off_topic = rej_generic = 0
    federal_count = 0
    rej_other_country = 0
    for (orig_name, u), summ in zip(valid_pairs, summaries):
        if not isinstance(summ, dict):
            continue
        text = summ.get("text") or ""
        site_name = (summ.get("org_name") or "").strip()

        # Регион сайта. Возможные значения:
        #   "" — TLD/контент не дали сигнала (международный домен .com, .org).
        #        Это глобальные бренды-производители (Bosch, Varta) — оставляем,
        #        ИИ называет их в контексте ниши, у клиента может быть как
        #        перепродажа этих брендов.
        #   == client_country — сайт в регионе клиента, пропускаем.
        #   != client_country (конкретно другая страна) — региональный магазин
        #        из другой страны. Для клиента это не «контекст ниши», это
        #        просто чужой рынок. ОТСЕИВАЕМ.
        site_country = country_from_site(u, text) if client_country else ""
        if client_country and site_country and site_country != client_country:
            rej_other_country += 1
            continue

        # is_player_in_other_market используется для бейджа в UI:
        # сайт без явной страны (Bosch.com) → True, помечается «федеральный/
        # республиканский игрок». Сайт в стране клиента → False, обычная строка.
        is_player_in_other_market = (
            not site_country
            or (client_country and site_country != client_country)
        )
        # Категория Block Б: строгий ≥2 вхождения стема (равно Блоку А).
        if not _site_matches_category(text, keywords, min_total=2):
            rej_off_topic += 1
            continue

        # Имя: site_name (без юр.формы) → orig_name (без юр.формы) → домен.
        # «ООО Стиген»/«ИП Гринь» → лучше показать stigen.by/akb-grin.by:
        # для клиента это узнаваемее, чем юр.имя.
        def _ok(n: str) -> bool:
            return (
                bool(n)
                and not looks_generic_name(n)
                and not is_placeholder_name(n)
                and not _starts_with_legal_form(n)
            )
        domain_label = (_domain_of(u) or "").lower()
        if _ok(site_name):
            name = site_name
        elif _ok(orig_name):
            name = orig_name
        else:
            name = domain_label
        if not name:
            rej_generic += 1
            continue
        nl = name.lower()
        if nl in seen or nl in block_a_lc or nl == brand_lc:
            continue
        seen.add(nl)
        out.append(name)
        meta[nl] = {
            "is_other_market": is_player_in_other_market,
            "site_country": site_country or "",
        }
        if is_player_in_other_market:
            federal_count += 1
        if len(out) >= count:
            break

    logger.info(
        "ai_mentioned_in_niche",
        candidates=len(ai_names),
        with_url=len(valid_pairs),
        accepted=len(out),
        other_market_players=federal_count,
        rej_off_topic=rej_off_topic,
        rej_other_country=rej_other_country,
        rej_generic=rej_generic,
    )
    return out, meta


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
