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
# Если поддомен заканчивается на один из этих хостов — отказ.
# Список взят из ТЗ + расширен очевидными.
BLACKLIST_DOMAINS = {
    # Соцсети
    "vk.com",
    "instagram.com",
    "facebook.com",
    "ok.ru",
    "t.me",
    "telegram.org",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    # Маркетплейсы
    "ozon.ru",
    "wildberries.ru",
    "wb.ru",
    "ali.com",
    "aliexpress.ru",
    "aliexpress.com",
    "yandex.market",
    "market.yandex.ru",
    "sbermegamarket.ru",
    "megamarket.ru",
    # Объявления / агрегаторы
    "avito.ru",
    "youla.ru",
    "drom.ru",
    "auto.ru",
    "cian.ru",
    "domclick.ru",
    # Карты / справочники
    "2gis.ru",
    "yandex.ru",
    "ya.ru",
    "google.com",
    "google.ru",
    # Туризм
    "tripadvisor.ru",
    "tripadvisor.com",
    "booking.com",
    "ostrovok.ru",
    "tutu.ru",
    "aviasales.ru",
    # Прочие конструкторы / агрегаторы услуг
    "tilda.ws",
    "tilda.cc",
    "tildacdn.com",
    "wix.com",
    "wixsite.com",
    "ucoz.ru",
    "narod.ru",
    "profi.ru",
    "yandex.uslugi",
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
            "Инструмент работает с сайтами компаний, не с профилями на "
            "агрегаторах и соцсетях. Если у вас сайт только на Авито/ВК/"
            "маркетплейсе — напишите нам напрямую.",
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
