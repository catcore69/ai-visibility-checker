"""Валидация URL клиента перед запуском pipeline.

Зачем (по ТЗ Этап 1.2):
- Инструмент имеет смысл ТОЛЬКО для клиентов, у которых уже есть сайт.
- Профили на агрегаторах/соцсетях (Авито, ВК, Озон, 2ГИС…) — это отдельная
  воронка через consultation, сюда их не пускаем.
- Если URL невалиден / сайт не отвечает — pipeline всё равно бы упал
  на site-fetcher'е; лучше отсечь раньше с понятной ошибкой.
"""

import re
from typing import Tuple
from urllib.parse import urlparse

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Чёрный список агрегаторов, соцсетей, маркетплейсов.
# Если поддомен заканчивается на один из этих хостов — отказ на /check.
# Синхронизирован с _COMPETITOR_URL_BLACKLIST в competitor_finder.py
# (одна правда — что не годится как клиент, то и не годится как конкурент).
BLACKLIST_DOMAINS = {
    # Соцсети и мессенджеры
    "vk.com", "instagram.com", "facebook.com", "ok.ru",
    "t.me", "telegram.org", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "linkedin.com",
    # Маркетплейсы РФ
    "ozon.ru", "wildberries.ru", "wb.ru",
    "ali.com", "aliexpress.ru", "aliexpress.com",
    "yandex.market", "market.yandex.ru",
    "sbermegamarket.ru", "megamarket.ru",
    "lamoda.ru", "citilink.ru", "mvideo.ru", "eldorado.ru", "dns-shop.ru",
    # Маркетплейсы и крупный ритейл РБ
    "21vek.by", "kufar.by", "av.by", "hata.by", "deal.by",
    "relax.by", "onliner.by", "praca.by", "rabota.by",
    "salonbel.by", "1prof.by",
    "oz.by", "5element.by", "electrosila.by",
    # Объявления / автоагрегаторы
    "avito.ru", "youla.ru", "drom.ru", "auto.ru",
    "abw.by", "auto.by", "autobild.by", "carmania.by",
    "drive2.ru", "drive2.by", "kolesa.kz",
    # Недвижимость (отдельная вертикаль, не «компания»)
    "cian.ru", "domclick.ru", "n1.ru", "m2.ru", "realty.yandex.ru",
    "gohome.by", "n1.by", "realt.by", "domovita.by",
    # Карты / поисковики / справочники
    "2gis.ru", "2gis.by",
    "yandex.ru", "ya.ru", "yandex.by",
    "google.com", "google.ru", "google.by", "maps.google.com",
    "spr.by", "flamp.ru", "flamp.by", "rejting.by",
    # Энциклопедии / новостные порталы (не «компания»)
    "wikipedia.org", "ru.wikipedia.org", "be.wikipedia.org",
    "tut.by", "sb.by", "belta.by", "rbc.ru", "lenta.ru",
    # Бизнес-реестры и каталоги юрлиц
    "checko.ru", "rusprofile.ru", "list-org.com", "sbis.ru", "kontur.ru",
    "nalog.ru", "nalog.gov.ru", "egrul.nalog.ru", "egr.gov.by",
    "spravka.ru", "yell.ru", "zoon.ru", "zoon.by",
    "vitebsk.biz", "minsk.biz", "by.biz", "byinform.com",
    # Госпорталы и образование
    "gov.by", "gov.ru", "gosuslugi.ru", "mos.ru",
    "edu.by", "edu.ru",
    # Телеком-операторы (это инфраструктура, не «компания в нише»)
    "a1.by", "mts.by", "mts.ru", "life.com.by", "lifeforyou.by",
    "belka.by", "velcom.by", "beltelecom.by", "byfly.by",
    "megafon.ru", "tele2.ru", "beeline.ru", "rostelecom.ru",
    # Туризм / агрегаторы услуг (отдельные платформы бронирования)
    "tripadvisor.ru", "tripadvisor.com", "booking.com",
    "ostrovok.ru", "tutu.ru", "aviasales.ru",
    "101hotels.com", "101hotels.ru", "hotels.com",
    "sutochno.ru", "tvil.ru", "bronevik.com", "otello.ru",
    "agoda.com", "airbnb.com", "airbnb.ru", "expedia.com",
    "hotellook.ru", "hotellook.com", "trivago.ru", "trivago.com",
    "tury.ru", "vse-otely.ru", "tonkosti.ru", "oktogo.ru",
    "suntime.ru", "level.travel", "travelata.ru", "onlinetours.ru",
    "tripster.ru", "sputnik8.com", "skyscanner.ru", "kupibilet.ru",
    # Email/портальные сервисы — почтовые ящики у компании не «бренд»
    "mail.ru", "rambler.ru",
    # Конструкторы сайтов и поддомены — это профиль на платформе, не сайт компании
    "tilda.ws", "tilda.cc", "tildacdn.com",
    "wix.com", "wixsite.com",
    "ucoz.ru", "narod.ru",
    "profi.ru", "yandex.uslugi",
}


# Минимальный regex для домена. Полную валидацию делает HEAD-запрос.
_URL_RE = re.compile(r"^[a-z0-9.\-]+\.[a-z]{2,}(:\d+)?(/.*)?$", re.IGNORECASE)


def _normalize(url: str) -> str:
    """Нормализует URL: добавляет схему, обрезает пробелы."""
    url = url.strip()
    if not url:
        return ""
    # Если ввели только домен — добавляем https://
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


def _is_blacklisted(domain: str) -> bool:
    domain = domain.lower().lstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    for b in BLACKLIST_DOMAINS:
        if domain == b or domain.endswith("." + b):
            return True
    return False


async def validate_url(url: str, do_head_check: bool = True) -> Tuple[bool, str, str]:
    """Проверяет URL клиента.

    Возвращает (is_valid, normalized_url, error_message).
    Если is_valid=True, error_message пустая.
    """
    # 1. Базовая нормализация
    normalized = _normalize(url)
    if not normalized:
        return False, "", "Введите адрес сайта."

    # 2. Парсинг
    try:
        parsed = urlparse(normalized)
    except Exception:
        return False, normalized, "Не похоже на корректный адрес сайта."

    netloc = (parsed.netloc or "").strip()
    if not netloc:
        return False, normalized, "Не похоже на корректный адрес сайта."

    # 3. Формальная проверка домена
    host = netloc.split(":")[0]
    if not _URL_RE.match(host):
        return False, normalized, "Не похоже на корректный адрес сайта."

    # 4. Чёрный список
    if _is_blacklisted(host):
        return (
            False,
            normalized,
            "Инструмент работает с сайтами компаний-производителей и "
            "сервисов, а не с маркетплейсами, агрегаторами, профилями в "
            "соцсетях и каталогами. Если у вас именно такая площадка — "
            "напишите нам напрямую: info@catcore.ru, и мы подскажем, что "
            "подойдёт под вашу задачу.",
        )

    # 5. HEAD-запрос (опционально, можно отключить в тестах)
    if not do_head_check:
        return True, normalized, ""

    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; CatCoreAIVisibilityBot/1.0; "
                    "+https://catcore.ru)"
                ),
            },
        ) as client:
            try:
                response = await client.head(normalized)
                # Некоторые серверы не разрешают HEAD — пробуем GET (без чтения тела)
                if response.status_code in (405, 501):
                    response = await client.get(normalized)
            except httpx.HTTPError:
                # На случай если HEAD блокируется на уровне WAF — fallback на GET
                response = await client.get(normalized)
    except httpx.TimeoutException:
        return False, normalized, "Сайт не ответил за 10 секунд. Проверьте адрес."
    except httpx.RequestError as exc:
        logger.warning("url_validate_request_error", url=normalized, error=str(exc))
        return False, normalized, "Не удалось открыть сайт. Проверьте адрес."
    except Exception as exc:
        # Не блокируем — даём pipeline'у попробовать. Логируем неожиданное.
        logger.warning("url_validate_unexpected", url=normalized, error=str(exc))
        return True, normalized, ""

    if response.status_code >= 400:
        return (
            False,
            normalized,
            f"Сайт не отвечает (код {response.status_code}). Проверьте адрес.",
        )

    return True, normalized, ""
