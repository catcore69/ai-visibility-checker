"""Справочник авторитетных площадок по регионам (Итерация-3, Задача 3).

Чинит баг: LLM «придумывала» рекомендовать vc.ru белорусскому клиенту.
Площадки берём ИЗ ЭТОГО СПРАВОЧНИКА (реальные факты), а LLM лишь оформляет
текст рекомендаций по переданным фактам — не выдумывает площадки сама.

Пополнять руками по мере выхода на новые регионы/ниши.
"""

from typing import Optional

REGIONAL_PLATFORMS: dict[str, dict[str, list[str]]] = {
    "РФ": {
        "general": ["vc.ru", "habr.com", "pikabu.ru", "dzen.ru"],
        "B2B": ["vc.ru", "rb.ru", "kommersant.ru"],
        "отзывы": ["otzovik.com", "irecommend.ru", "Яндекс.Карты", "2ГИС"],
    },
    "Беларусь": {
        "general": ["dev.by", "probusiness.io", "onliner.by"],
        "B2B": ["probusiness.io", "dev.by", "Office Life", "myfin.by"],
        "отзывы": ["Яндекс.Карты", "flamp.by", "Google Maps", "rejting.by"],
    },
}

# Дефолт, если регион не распознан как РФ/РБ — берём РФ-общие + помечаем,
# что точные площадки уточнит эксперт (не выдумываем локальные для неизвестной страны).
_DEFAULT_REGION_KEY = "РФ"


def _region_key(region: str) -> str:
    """Нормализует строку региона отчёта в ключ справочника."""
    r = (region or "").lower()
    if "беларус" in r or "рб" in r or r.endswith(".by") or "минск" in r or "витебск" in r \
            or "гомел" in r or "брест" in r or "гродн" in r or "могил" in r:
        return "Беларусь"
    return _DEFAULT_REGION_KEY


def get_platforms_for(region: str, audience: Optional[str] = None) -> list[str]:
    """Возвращает плоский список рекомендуемых площадок для региона.

    audience: "B2B"/"B2C" из niche.target_audience — влияет на акцент.
    Берём B2B-список (если бизнес B2B) либо general + всегда добавляем «отзывы».
    """
    key = _region_key(region)
    block = REGIONAL_PLATFORMS.get(key, REGIONAL_PLATFORMS[_DEFAULT_REGION_KEY])

    aud = (audience or "").upper()
    primary = block["B2B"] if "B2B" in aud else block["general"]

    out: list[str] = []
    seen: set[str] = set()
    for item in primary + block.get("отзывы", []):
        if item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


def region_is_known(region: str) -> bool:
    """True, если регион распознан явно (РФ/РБ), а не дефолт."""
    return _region_key(region) in REGIONAL_PLATFORMS and (
        "беларус" in (region or "").lower()
        or "рб" in (region or "").lower()
        or "росси" in (region or "").lower()
        or "рф" in (region or "").lower()
    )
