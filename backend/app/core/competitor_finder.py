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
    # Доски объявлений / классифайды (включая региональные) — не конкуренты,
    # это площадки. farpost.ru — ДВ-аналог Авито.
    "farpost.ru", "irr.ru", "barahla.net", "slando.ru", "unibo.ru",
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
    # Каталоги турбаз / отдыха / походов — не отдельные базы, а справочники
    "mirturbaz.ru", "turbazy.ru", "baza-otdyha.ru", "vse-otdyh.ru",
    "tropki.ru", "tropa.ru", "marshruty.ru", "nature-travel.ru",
    "kuda-sxodit.ru", "kudago.com", "trip-point.ru", "otdyhwithdetmi.ru",
    # Региональные порталы (новости, каталоги, форумы — не отдельные компании)
    "dvhab.ru", "dv.land", "dvnovosti.ru", "amurmedia.ru", "primamedia.ru",
    "khabarovsk.bezformata.com", "vl.ru", "newsvl.ru",
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


# ГЛОБАЛЬНЫЙ фильтр «информационный ресурс / агрегатор / каталог», а не
# сайт компании-конкурента. ТЗ catcore-dogon-3-pravki (разбор e2a20204):
# citations Google AI Overview и часть SERP — это отзовики (otzovik),
# вики (gorodwiki), порталы (shamora), агрегаторы (booking-подобные),
# рейтинги/каталоги. Они САМИ пишут про нишу, поэтому категория-фильтр их
# не ловит. Отсекаем по КЛАССУ домена (подстроки), а не по конкретному
# домену — механика работает для любой ниши и региона.
_INFO_RESOURCE_DOMAIN_PATTERNS = (
    # Отзывы/рейтинги
    "otzovik", "otzyv", "otziv", "irecommend", "review", "feedback",
    "reiting", "rating", "ratings", "top10", "top-10", "vsе-otzyvy",
    # Вики/справочники/энциклопедии
    "wiki", "gorodwiki", "spravochnik", "spravka", "encyclop",
    # Порталы/новости/форумы/афиши
    "portal", "forum", "novosti", "news", "afisha", "gorod-",
    "-gorod", "gorods", "bezformata", "blizko", "regionz",
    # Каталоги/агрегаторы/маркетплейсы услуг
    "katalog", "catalog", "agregator", "spisok", "navigator",
    "vsе-", "all-", "найди", "poisk", "search",
    # Агрегаторы бронирования (для туризма/отелей/баз) — каналы, не компании
    "booking", "bron", "zabronirui", "ostrovok", "sutochno",
    # Карты/геосервисы
    "2gis", "yandex", "google", "maps",
)


def _is_info_resource(host: str) -> bool:
    """True, если домен по классу — информационный ресурс/агрегатор/каталог,
    а не сайт одной компании-конкурента. Подстрочный матч по host (без TLD-
    шума): «otzovik.com», «gorodwiki.ru», «my-portal.info» → True.

    Глобально, не под конкретный кейс: ловит КЛАСС сайтов.
    """
    h = (host or "").lower()
    if not h:
        return False
    # Берём «тело» домена без зоны для проверки подстрок (otzovik.com → otzovik).
    core = h
    for sep in (".",):
        # оставляем всё до последней точки + sasubdomain'ы — проверяем целиком
        pass
    for pat in _INFO_RESOURCE_DOMAIN_PATTERNS:
        if pat in core:
            return True
    return False


# Порог детектора каталога/агрегатора по числу разных городов в тексте сайта.
# Одна локальная компания привязана к 1-2 городам (свой город + иногда край/
# соседний). Каталог (domik.travel, 101hotels, агрегатор бухгалтерий) листит
# десятки. 5 — безопасный зазор: реальный бизнес почти никогда не упоминает
# 5 РАЗНЫХ городов из газеттира, а каталог — всегда.
_CATALOG_CITY_THRESHOLD = 5


def _looks_like_catalog(text: str) -> bool:
    """True, если сайт по контенту — каталог/агрегатор (покрывает много
    городов), а не одна компания-конкурент.

    Корневая причина бага 800b4eca: domik.travel прошёл и блэклист (его там
    нет), и класс-фильтр `_is_info_resource` (в хосте нет booking/katalog/...),
    и категория-фильтр (на листинге сотен баз слово «отдых» встречается
    десятки раз). Отличить от одной базы можно по охвату городов. Сигнал
    нишево-независимый: одинаково ловит каталоги баз отдыха, бухгалтерий и
    магазинов аккумуляторов.
    """
    if not text:
        return False
    try:
        from app.core.region_detector import count_distinct_cities
        return count_distinct_cities(text) >= _CATALOG_CITY_THRESHOLD
    except Exception:
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
            if not host or _is_blacklisted_host(host) or _is_info_resource(host):
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
            if not host or _is_blacklisted_host(host) or _is_info_resource(host):
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


# Браузерные заголовки — XMLRiver без них режет русские запросы в антибот
# (error 15) и не отдаёт <localresultsplace>. Подтверждено разведкой ЭТАПА 0.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


async def _fetch_business_cards(query: str, num: int = 20) -> list[dict]:
    """ТЗ catcore-tipy-biznesa, ветка LOCAL источник №1: карточки бизнеса
    Google (`<localresultsplace>`) из ОБЫЧНОЙ выдачи /search/xml.

    Разведка ЭТАПА 0 установила:
    - Карточки приходят на ГОЛЫЙ запрос query+user+key + браузерный UA.
      Параметры setab/loc/country/additional их ЛОМАЮТ (error 15/500).
    - Регион вшивается в текст query («база отдыха в хабаровском крае»).
    - Транзиентный error 500 «Выполните перезапрос» — ретраим.
    - Поля карточки: <title>, <url>, <rating>. url может быть реальным
      сайтом ИЛИ ссылкой /maps/dir/... (тогда сайт ищем по title отдельно).

    Возвращает [{title, url, rating, has_site}], где has_site=False если
    url — это /maps/dir/ (не сайт компании).
    """
    if not settings.XMLRIVER_USER or not settings.XMLRIVER_KEY:
        return []
    if not query or not query.strip():
        return []

    text = ""
    for attempt in range(4):
        try:
            async with httpx.AsyncClient(timeout=30.0, headers=_BROWSER_HEADERS) as client:
                resp = await client.get(
                    "https://xmlriver.com/search/xml",
                    params={
                        "user": settings.XMLRIVER_USER,
                        "key": settings.XMLRIVER_KEY,
                        "query": query,
                        "count": str(num),
                    },
                )
                resp.raise_for_status()
            text = resp.text
        except Exception as exc:
            logger.warning("business_cards_http_error", query=query[:60], error=str(exc))
            return []
        # Транзиентный error 500 «Выполните перезапрос» — повторяем.
        if '<error code="500"' in text:
            await asyncio.sleep(1.5)
            continue
        break

    out: list[dict] = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        logger.warning("business_cards_parse_error", query=query[:60])
        return []

    for item in root.findall(".//localresultsplace/item"):
        title_el = item.find("title")
        url_el = item.find("url")
        rating_el = item.find("rating")
        title = (title_el.text or "").strip() if title_el is not None else ""
        url = (url_el.text or "").strip() if url_el is not None else ""
        rating = (rating_el.text or "").strip() if rating_el is not None else ""
        if not title:
            continue
        # url вида http:///maps/dir/... или google maps — это НЕ сайт компании.
        has_site = bool(
            url
            and url.startswith(("http://", "https://"))
            and "/maps/" not in url
            and "google." not in url.lower()
            and _domain_of(url)
        )
        out.append({
            "title": title,
            "url": url if has_site else "",
            "rating": rating,
            "has_site": has_site,
        })

    logger.info(
        "business_cards_fetched",
        query=query[:60],
        cards=len(out),
        with_site=sum(1 for c in out if c["has_site"]),
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

    # ТЗ catcore-dogon-3-pravki Правка 1: SERP-запрос Блока А строится из
    # primary_category — это РЫНОЧНЫЙ поисковый термин («база отдыха»,
    # «аккумуляторы», «бухгалтерские услуги»), тот же, по которому идут
    # запросы к моделям. НЕ из subcategory/самоназвания («агроусадьба»):
    # самоназвание не ищется в регионе клиента и даёт sparse.
    # primary_category теперь нормализован промптом до поискового термина
    # (не широкая надкатегория «автотовары», не экзотическое «агроусадьба»).
    from app.core.niche_detector import primary_category, primary_subcategory
    p_cat = primary_category(niche)
    p_sub = primary_subcategory(niche)
    primary = _clean_phrase(p_cat) or _clean_phrase(p_sub) or p_cat.strip()
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
        short_primary = _first_keyword(p_cat) or _first_keyword(p_sub)
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

    # Уникальные реальные домены (без агрегаторов/соцсетей и без домена клиента).
    excl_domains: set[str] = {
        e.strip().lower()
        for e in (exclude or [])
        if e and "." in e and " " not in e
    }
    seen_domains: set[str] = set()
    real_urls: list[str] = []
    for r in results:
        d = (r.get("domain") or "").lower()
        if not d or _is_blacklisted_host(d) or _is_info_resource(d):
            continue
        if d in seen_domains or d in excl_domains:
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
    rej_catalog = 0
    for u, summ in zip(real_urls, summaries):
        if not isinstance(summ, dict):
            continue
        text = summ.get("text") or ""
        org_name = (summ.get("org_name") or "").strip()

        # Конъюнктивный confidence-фильтр. Сначала проверяем, что САЙТ нам подходит
        # (регион + категория), и ТОЛЬКО ПОТОМ решаем по имени. Если сайт реальный
        # и наш, но имя метаданных мусорное — оставляем кандидата с доменом-меткой,
        # а не теряем реального конкурента (buhvitebsk.by — реальная фирма).

        # 0. Каталог/агрегатор (покрывает много городов) — НЕ конкурент.
        # Ловит domik.travel/101hotels, которых нет ни в блэклисте, ни в
        # класс-фильтре по хосту, но которые проходят категорию (листинг).
        if _looks_like_catalog(text):
            rej_catalog += 1
            continue
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
        rej_catalog=rej_catalog,
        keywords=keywords,
        client_country=client_country,
    )
    return out


def _category_keywords(niche: dict[str, Any]) -> list[str]:
    """ТЗ catcore-5-globalnyh-fiksov Фикс 1: стемы категория-фильтра.

    Иерархия источников:
      1. primary_subcategory — узкие, специфичные стемы (агроусадьба, аккумуляторы,
         аутсорс). Этого ОБЫЧНО достаточно, и это правильный приоритет.
      2. Если subcategory дала пустые стемы — fallback на primary_category.
      3. Стоп-лист — _CATEGORY_STEM_STOPS (только служебные/гео/общие шапки).

    Зачем приоритет узкого: широкое «база отдыха» содержит стем «отдых-»,
    который сработает на турагентстве (lider-tour.ru: «отдых на море»).
    Узкое «агроусадьба» даёт стем «агроус-» — у турагентства его нет.

    На 3 кейсах:
    - Манома: p_sub=«агроусадьба» → ['агроус'] (отрезает турагентства)
    - Витебск: p_sub=«бухгалтерский аутсорс» → ['бухгал','аутсор']
    - Минск: p_sub=«аккумуляторы» → ['аккуму']
    """
    from app.core.site_analyzer import _CATEGORY_STEM_STOPS
    from app.core.niche_detector import primary_category, primary_subcategory

    def _stems_from(phrase: str) -> list[str]:
        raw = (phrase or "").lower()
        tokens = [t.strip("«»\"'.,()-—:;") for t in raw.split() if t]
        distinctive = [
            t for t in tokens
            if t and t not in _CATEGORY_STEM_STOPS and len(t) >= 5
        ]
        return list({t[:6] for t in distinctive})

    # ТЗ catcore-dogon-3-pravki Правка 1: стемы фильтра — из primary_category
    # (тот же поисковый термин, что и SERP-запрос). primary_category теперь
    # нормализован промптом до рыночного термина: «база отдыха»→['отдыха'],
    # «аккумуляторы»→['аккуму'], «бухгалтерские услуги»→['бухгал'].
    # Дополняем стемами из subcategory (если они различны) — для точности,
    # но primary_category первичен.
    p_cat = primary_category(niche)
    p_sub = primary_subcategory(niche)
    stems = set(_stems_from(p_cat))
    stems |= set(_stems_from(p_sub))
    if stems:
        return list(stems)
    # Если оба пустые (всё в стопе) — короткие слова <5 берём целиком,
    # чтобы фильтр не остался без ключей и не пропускал всё.
    raw = " ".join([p_cat, p_sub]).lower()
    short = [
        t.strip("«»\"'.,()-—:;")
        for t in raw.split()
        if t and t.strip("«»\"'.,()-—:;") not in _CATEGORY_STEM_STOPS
    ]
    return list({t[:6] for t in short if t})


def _site_matches_category(text: str, keywords: list[str], min_total: int = 2) -> bool:
    """True, если сайт реально про эту категорию.

    Итерация-3: одного вхождения мало — «Юрист для людей» иногда упоминает
    «бухгалтерские услуги» в списке смежных услуг, но это не бухгалтерская
    фирма. Требуем СУММУ вхождений всех стемов категории ≥ min_total.

    ТЗ catcore-5-globalnyh-fiksov Фикс 1: пустой keywords БОЛЬШЕ НЕ
    пропускает всё подряд (раньше `return True` создавал дыру —
    «Московский Комсомолец» в Block A магазина АКБ). Если категория не
    смогла собраться в стемы — это ошибка построения ниши, лучше
    показать меньше конкурентов, чем пропустить мусор.
    """
    if not keywords:
        logger.warning("category_filter_empty_keywords_reject_all")
        return False
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

    from app.core.site_analyzer import (
        looks_generic_name,
        looks_like_slogan,
        is_placeholder_name,
    )
    brand_l = (brand_name or "").strip().lower()
    counter: dict[str, int] = {}
    canonical: dict[str, str] = {}  # lower → оригинальное написание
    for lst in results:
        for name in lst:
            n = name.strip()
            nl = n.lower()
            if (
                not n
                or nl == brand_l
                or looks_generic_name(n)
                or looks_like_slogan(n)
                or is_placeholder_name(n)
            ):
                continue
            counter[nl] = counter.get(nl, 0) + 1
            canonical.setdefault(nl, n)

    ranked = sorted(counter.items(), key=lambda kv: -kv[1])
    out = [canonical[nl] for nl, _ in ranked][:max_brands]
    logger.info("brands_from_ai_responses", found=len(out), candidates=list(counter.keys())[:10])
    return out


async def _find_competitors_from_cards(
    niche: dict[str, Any],
    brand_name: str,
    exclude: list[str],
    count: int = 5,
) -> list[str]:
    """ТЗ catcore-tipy-biznesa, LOCAL источник №1: конкуренты из карточек
    бизнеса Google (`<localresultsplace>`).

    Карточки по ПРИРОДЕ — реальные компании с гео-привязкой (Google local
    pack отбирает по запросу «<категория> <регион>»). Агрегаторы/отзовики/
    вики карточек в категории не имеют → отсекаются сами.

    Логика по каждой карточке:
    - имя = <title> (чистое имя компании); прогоняем через slogan/generic/
      placeholder/legal-form фильтры;
    - если у карточки есть сайт (has_site) → fetch_site_summary, проверяем
      регион+категорию по тексту сайта (как для SERP);
    - если сайта нет (url=/maps/dir/) → find_competitor_url(title) ищет сайт
      в органике (твоё замечание). Нашёлся — проверяем. Не нашёлся — карточка
      всё равно валидна (Google local pack уже подтвердил нишу+гео), берём
      по title без site-аудита.
    """
    from app.core.site_analyzer import (
        fetch_site_summary,
        looks_generic_name,
        is_placeholder_name,
        looks_like_slogan,
        country_from_site,
    )
    from app.core.niche_detector import primary_category, primary_subcategory

    region = niche.get("region", "")
    client_country = _client_country(region)
    city = _city_from_region(region) or region
    p_cat = primary_category(niche)
    # Запрос карточек = рыночный термин + регион (текстом), напр.
    # «база отдыха Хабаровский край».
    card_query = " ".join(p for p in [p_cat, city] if p).strip()
    if not card_query:
        return []

    cards = await _fetch_business_cards(card_query, num=20)
    if not cards:
        logger.info("competitors_from_cards_empty", brand=brand_name, query=card_query)
        return []

    excl_lower = {e.strip().lower() for e in (exclude or []) if e}
    brand_lc = (brand_name or "").lower()
    keywords = _category_keywords(niche)

    def _ok_name(n: str) -> bool:
        return (
            bool(n)
            and not looks_generic_name(n)
            and not is_placeholder_name(n)
            and not looks_like_slogan(n)
            and not _starts_with_legal_form(n)
        )

    # Сначала находим сайты для карточек без сайта (параллельно).
    cards_need_site = [c for c in cards if not c["has_site"] and _ok_name(c["title"])]
    found_urls = await asyncio.gather(
        *[find_competitor_url(c["title"], region) for c in cards_need_site],
        return_exceptions=True,
    )
    site_by_title: dict[str, str] = {}
    for c, u in zip(cards_need_site, found_urls):
        if isinstance(u, str) and u:
            site_by_title[c["title"]] = u

    # Теперь итог: для каждой карточки определяем url (свой или найденный).
    out: list[str] = []
    seen: set[str] = set()
    rej_generic = rej_off_topic = rej_wrong_country = 0
    cards_with_url = []
    for c in cards:
        title = c["title"]
        if not _ok_name(title):
            rej_generic += 1
            continue
        url = c["url"] or site_by_title.get(title, "")
        cards_with_url.append((c, url))

    # Параллельно тянем summary тех, у кого есть url (для регион+категория проверки).
    urls_to_fetch = [u for _, u in cards_with_url if u]
    summaries = await asyncio.gather(
        *[fetch_site_summary(u) for u in urls_to_fetch], return_exceptions=True
    )
    summ_by_url = {}
    si = 0
    for _, u in cards_with_url:
        if u:
            summ_by_url[u] = summaries[si] if si < len(summaries) else None
            si += 1

    for c, url in cards_with_url:
        title = c["title"]
        domain_label = _domain_of(url).lower() if url else ""
        summ = summ_by_url.get(url) if url else None
        text = summ.get("text") if isinstance(summ, dict) else ""

        # Регион + категория проверяем ТОЛЬКО если есть сайт с текстом.
        # Если сайта нет — доверяем карточке (Google local pack гео+ниша).
        if url and isinstance(summ, dict) and text:
            # Каталог/агрегатор (много городов) — не отдельный конкурент.
            if _looks_like_catalog(text):
                rej_off_topic += 1
                continue
            if client_country:
                site_country = country_from_site(url, text)
                if site_country and site_country != client_country:
                    rej_wrong_country += 1
                    continue
            if keywords and not _site_matches_category(text, keywords, min_total=2):
                rej_off_topic += 1
                continue

        # Имя: site_name (если сайт дал нормальное) → title карточки → домен.
        name = title
        if isinstance(summ, dict):
            sn = (summ.get("org_name") or "").strip()
            if _ok_name(sn):
                name = sn
        nl = name.lower()
        if nl in excl_lower or nl in seen or nl == brand_lc:
            continue
        seen.add(nl)
        out.append(name)
        if len(out) >= count:
            break

    logger.info(
        "competitors_from_cards",
        query=card_query,
        cards=len(cards),
        accepted=len(out),
        rej_generic=rej_generic,
        rej_off_topic=rej_off_topic,
        rej_wrong_country=rej_wrong_country,
    )
    return out


async def fetch_card_competitor_names(
    niche: dict[str, Any],
    brand_name: str = "",
    max_names: int = 12,
) -> list[str]:
    """Лёгкий список ИМЁН конкурентов из карточек бизнеса Google —
    для стоп-листа брендов в запросах (ТЗ-разбор 800b4eca: «база отдыха
    белое озеро», «турбаза узала» — навигация к конкретному заведению,
    не запрос ниши). В отличие от `_find_competitors_from_cards` НЕ заходит
    на сайты (не нужен аудит региона/категории), берём только чистые title.

    Карточки — точный источник имён собственных локальных игроков той же
    ниши/региона. Вызывается в пайплайне ДО отбора запросов; имена идут
    селектору как exclude + детерминированно вырезают запросы с ними.
    Механика общая для любой LOCAL-ниши.
    """
    from app.core.site_analyzer import (
        looks_generic_name,
        is_placeholder_name,
        looks_like_slogan,
    )
    from app.core.niche_detector import primary_category

    region = niche.get("region", "")
    city = _city_from_region(region) or region
    p_cat = primary_category(niche)
    card_query = " ".join(p for p in [p_cat, city] if p).strip()
    if not card_query:
        return []
    try:
        cards = await _fetch_business_cards(card_query, num=20)
    except Exception as exc:
        logger.warning("card_names_fetch_failed", error=str(exc))
        return []

    brand_lc = (brand_name or "").lower()
    out: list[str] = []
    seen: set[str] = set()
    for c in cards or []:
        t = (c.get("title") or "").strip()
        tl = t.lower()
        if not t or tl in seen or tl == brand_lc:
            continue
        if (
            looks_generic_name(t)
            or is_placeholder_name(t)
            or looks_like_slogan(t)
            or _starts_with_legal_form(t)
        ):
            continue
        seen.add(tl)
        out.append(t)
        if len(out) >= max_names:
            break
    logger.info("card_names_for_query_stoplist", query=card_query, names=len(out))
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
                if not d or _is_blacklisted_host(d) or _is_info_resource(d):
                    continue
                if d in seen_domains:
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
        # Каталог/агрегатор (много городов) — не отдельный конкурент.
        if _looks_like_catalog(text):
            rej_off_topic += 1
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
        # Каталог/агрегатор (много городов) — не отдельный конкурент.
        if _looks_like_catalog(text):
            rej_off_topic += 1
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
    client_url: str = "",
    raw_responses: Optional[dict] = None,
) -> tuple[list[str], str, dict[str, str]]:
    """Блок А — МАРШРУТИЗАЦИЯ по business_scope (ТЗ catcore-tipy-biznesa).

    Общее начало для всех веток: клиентские конкуренты (форма). Если их ≥count
    — берём только их. Дальше — стратегия по типу бизнеса:

    LOCAL (локальный бизнес):
        карточки бизнеса Google → SERP-органика → citations Google+Yandex.
    ONLINE_FEDERAL / PERSONAL_BRAND (онлайн/федеральный/личный бренд):
        конкуренты из ОТВЕТОВ ИИ (для них ИИ знает игроков) → федеральная
        SERP-органика. Карточки не применимы (нет физической точки).

    Возвращает (names, overall_source, per_name_source_map).
    """
    from app.core.niche_detector import business_scope as _scope

    scope = _scope(niche)
    client_list = _normalize_client_competitors(client_competitors, brand_name)[:count]
    sources_map: dict[str, str] = {n.lower(): "client" for n in client_list}

    client_domain = _domain_of(client_url) if client_url else ""
    base_exclude = [brand_name] + client_list
    if client_domain:
        base_exclude.append(client_domain)

    if len(client_list) >= count:
        logger.info("competitors_from_client_only", count=len(client_list), brand=brand_name)
        return (client_list[:count], "client", {n: "client" for n in client_list[:count]})

    # ────────────────────────────────────────────────────────────────────
    # ВЕТКА LOCAL: карточки → органика → citations
    # ────────────────────────────────────────────────────────────────────
    if scope == "local":
        # Источник №1 — карточки бизнеса Google (localresultsplace).
        card_names: list[str] = []
        try:
            card_names = await _find_competitors_from_cards(
                niche, brand_name=brand_name, exclude=base_exclude,
                count=count - len(client_list),
            )
        except Exception as exc:
            logger.warning("cards_block_a_failed", error=str(exc))
        for n in card_names:
            sources_map.setdefault(n.lower(), "business_card")
        after_cards = _merge_dedupe(client_list, card_names, count)

        # Источник №2 — SERP-органика (дополнение).
        serp_names: list[str] = []
        if len(after_cards) < count:
            exclude = [brand_name] + after_cards + ([client_domain] if client_domain else [])
            try:
                serp_names = await _find_competitors_via_serp(
                    niche, exclude=exclude, count=count - len(after_cards)
                )
            except Exception as exc:
                logger.warning("serp_block_a_failed", error=str(exc))
            for n in serp_names:
                sources_map.setdefault(n.lower(), "serp_direct")
        after_serp = _merge_dedupe(after_cards, serp_names, count)

        # Источник №3 — citations Google AI Overview + Яндекс-Нейро (слитые).
        ai_names: list[str] = []
        if ai_citations and len(after_serp) < count:
            exclude = [brand_name] + after_serp + ([client_domain] if client_domain else [])
            try:
                ai_names = await _find_competitors_from_ai_citations(
                    niche, brand_name=brand_name, ai_citations=ai_citations,
                    exclude=exclude, count=count - len(after_serp),
                )
            except Exception as exc:
                logger.warning("ai_citations_block_a_failed", error=str(exc))
            for n in ai_names:
                sources_map.setdefault(n.lower(), "ai_overview")
        merged = _merge_dedupe(after_serp, ai_names, count)

        parts = []
        if card_names: parts.append("cards")
        if serp_names: parts.append("serp")
        if ai_names: parts.append("ai")
        source = ("client+" if client_list else "") + "+".join(parts) if parts else (
            "client" if client_list else "sparse"
        )
        if len(merged) < 3:
            source = "sparse"
            logger.info("competitors_sparse", count=len(merged), brand=brand_name, scope=scope)

    # ────────────────────────────────────────────────────────────────────
    # ВЕТКА ONLINE_FEDERAL / PERSONAL_BRAND: конкуренты из ответов ИИ → SERP
    # ────────────────────────────────────────────────────────────────────
    else:
        ai_resp_names: list[str] = []
        if raw_responses:
            try:
                ai_resp_names = await _find_competitors_from_ai_responses(
                    niche, brand_name=brand_name, raw_responses=raw_responses,
                    exclude=base_exclude, count=count - len(client_list),
                )
            except Exception as exc:
                logger.warning("ai_responses_block_a_failed", error=str(exc))
        for n in ai_resp_names:
            sources_map.setdefault(n.lower(), "ai_mentioned")
        after_ai = _merge_dedupe(client_list, ai_resp_names, count)

        # Федеральная SERP-органика как дополнение (region обычно «Россия»/онлайн
        # без города → запрос «<категория> Россия», _find_competitors_via_serp
        # сам не добавит город, если city пуст).
        serp_names = []
        if len(after_ai) < count:
            exclude = [brand_name] + after_ai + ([client_domain] if client_domain else [])
            try:
                serp_names = await _find_competitors_via_serp(
                    niche, exclude=exclude, count=count - len(after_ai)
                )
            except Exception as exc:
                logger.warning("serp_federal_failed", error=str(exc))
            for n in serp_names:
                sources_map.setdefault(n.lower(), "serp_direct")
        merged = _merge_dedupe(after_ai, serp_names, count)

        parts = []
        if ai_resp_names: parts.append("ai_responses")
        if serp_names: parts.append("serp")
        source = ("client+" if client_list else "") + "+".join(parts) if parts else (
            "client" if client_list else "sparse"
        )
        if len(merged) < 3:
            source = "sparse"
            logger.info("competitors_sparse", count=len(merged), brand=brand_name, scope=scope)

    logger.info("block_a_scope", scope=scope, source=source, count=len(merged))
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

    from app.core.niche_detector import business_scope as _bscope
    _scope_local = _bscope(niche) == "local"

    region = niche.get("region", "")
    ai_names = await extract_brands_from_ai_responses(raw_responses, brand_name, niche)
    if not ai_names:
        logger.info("ai_mentioned_in_niche_empty", brand=brand_name)
        return [], {}

    # Плейсхолдеры, generic, slogan и совпадения с Блоком А — выкидываем
    # до похода в SERP. ТЗ catcore-blok-a-iz-realnoy-vydachi:
    # «Отдых в гармонии с природой!» не должно быть в Блоке Б.
    #
    # ТЗ catcore-5-globalnyh-fiksov: дедуп Block A vs Block B — не только
    # по именам, но и по ДОМЕНАМ. «Заимка Узалы» (имя в Block B от ИИ)
    # и «zaimkauzala.ru» (имя-домен в Block A) — это один и тот же конкурент.
    block_a_lc = {n.lower() for n in (existing_block_a or [])}
    # Если имя в Block A выглядит как домен (содержит точку, без пробелов),
    # запомним его как «известный домен» для проверки URL'ов из Block B.
    block_a_domains: set[str] = {
        n.lower().strip()
        for n in (existing_block_a or [])
        if n and "." in n and " " not in n.strip()
    }
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
    # Дедуп по домену: если URL кандидата — уже в Block A, пропускаем
    # (даже если имена разные: «Заимка Узалы» vs «zaimkauzala.ru»).
    valid_pairs = []
    for n, u in zip(ai_names, urls):
        if not isinstance(u, str) or not u:
            continue
        d = _domain_of(u)
        if d and d.lower() in block_a_domains:
            continue
        valid_pairs.append((n, u))
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

        # ТЗ catcore-5-globalnyh-fiksov Фикс 4: Block Б не отсеивает по
        # региону, а ПОМЕЧАЕТ:
        #   - site_country == "" (международный .com/.org) → пометка «федерал»
        #   - site_country != client_country → пометка «федерал/международный»
        #   - site_country == client_country, но site_city != client_city
        #       (другой регион внутри страны) → пометка «из другого региона»
        #   - site_country == client_country, site_city == client_city →
        #       без пометки (локальный игрок)
        # Это валидный инсайт: «ИИ в вашей нише знает в основном неместные базы»
        # = «локально ниша свободна» (Сценарий 1).
        site_country = country_from_site(u, text) if client_country else ""

        # Определяем «другой регион внутри страны»:
        # Если у клиента есть конкретный город (region = «Город, Страна») И
        # site_country совпадает со страной клиента — проверяем, упоминается
        # ли client_city на сайте конкурента. Нет упоминания → другой регион.
        client_city = ""
        if client_country and region and "," in region:
            client_city = region.split(",")[0].strip().lower()
        is_other_region_same_country = False
        if (
            client_city
            and site_country
            and site_country == client_country
            and client_city not in (text or "").lower()
        ):
            is_other_region_same_country = True

        # is_player_in_other_market = True, если сайт НЕ подтверждён как
        # локальный (другая страна, нет страны, или другой регион внутри
        # страны). Используется как бейдж в UI.
        is_player_in_other_market = (
            not site_country
            or (client_country and site_country != client_country)
            or is_other_region_same_country
        )

        # ТЗ-разбор bb8e4724: для LOCAL-бизнеса Block Б — ТОЛЬКО регион клиента.
        # Базы из других регионов РФ не показываем хабаровскому клиенту. Если
        # site_country другой ИЛИ другой регион внутри страны — отсекаем.
        # Для online_federal/personal_brand — оставляем (там федералы уместны,
        # помечаются бейджем).
        if _scope_local and is_player_in_other_market:
            rej_other_country += 1
            continue

        # Каталог/агрегатор (много городов) — не игрок ниши.
        if _looks_like_catalog(text):
            rej_off_topic += 1
            continue
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
            "is_other_region": is_other_region_same_country,
            "site_country": site_country or "",
        }
        if is_player_in_other_market:
            federal_count += 1
        if is_other_region_same_country:
            rej_other_country += 1  # переиспользуем счётчик для логирования
        if len(out) >= count:
            break

    logger.info(
        "ai_mentioned_in_niche",
        candidates=len(ai_names),
        with_url=len(valid_pairs),
        accepted=len(out),
        other_market_players=federal_count,
        rej_off_topic=rej_off_topic,
        other_region_within_country=rej_other_country,
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
