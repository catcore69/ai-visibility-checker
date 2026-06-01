"""Определение региона бизнеса по жёстким сигналам сайта (Задача 4 срочного ТЗ).

Корень проблемы: раньше регион брался из формы (дефолт «Россия») или
«угадывался» моделью, которая по умолчанию считает русскоязычный бизнес
российским. Из-за этого витебский клиент получал регион «Россия», и вся
цепочка (конкуренты, запросы) ехала в РФ.

Здесь регион определяется парсингом главной страницы по иерархии сигналов
от сильного к слабому: TLD → телефоны → валюта/реквизиты → города.
ДЕФОЛТ «Россия» ЗАПРЕЩЁН: если сигналов нет — country="unknown",
confidence="low" (дальше можно спросить клиента / отдать LLM с явным
запретом предполагать Россию).
"""

import re
from collections import Counter
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
import tldextract

from app.utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; CatCoreAIVisibilityBot/1.0; +https://catcore.ru) "
    "AppleWebKit/537.36"
)

# ── TLD → страна ────────────────────────────────────────────────────────────
TLD_COUNTRY = {
    "by": "Беларусь",
    "ru": "Россия",
    "рф": "Россия",
    "su": "Россия",
    "kz": "Казахстан",
    "ua": "Украина",
    "uz": "Узбекистан",
    "kg": "Киргизия",
}

# ── Телефонные коды стран ───────────────────────────────────────────────────
# +375 — Беларусь, +7 — Россия/Казахстан, +380 — Украина, +998 — Узбекистан
# Для +375 — код города → город.
BY_CITY_CODES = {
    "17": "Минск", "162": "Брест", "152": "Гродно", "212": "Витебск",
    "222": "Могилёв", "232": "Гомель", "163": "Барановичи", "165": "Пинск",
    "214": "Полоцк", "216": "Новополоцк", "225": "Бобруйск", "236": "Жлобин",
    "1771": "Солигорск", "176": "Молодечно", "1774": "Борисов",
}

# ── РФ городские телефонные коды (после +7) → город ─────────────────────────
# Для определения конкретного города в РФ. Особенно важны Дальний Восток
# и Сибирь — типичная зона «потеряет регион → угадается Москва/Омск».
RU_CITY_CODES = {
    "495": "Москва", "499": "Москва", "812": "Санкт-Петербург",
    "383": "Новосибирск", "343": "Екатеринбург", "843": "Казань",
    "831": "Нижний Новгород", "351": "Челябинск", "846": "Самара",
    "381": "Омск", "863": "Ростов-на-Дону", "347": "Уфа",
    "391": "Красноярск", "473": "Воронеж", "342": "Пермь",
    "844": "Волгоград", "861": "Краснодар", "3452": "Тюмень",
    "845": "Саратов", "3412": "Ижевск",
    # Дальний Восток / Сибирь (зона «потери региона»)
    "4212": "Хабаровск", "423": "Владивосток", "4112": "Якутск",
    "4132": "Магадан", "4152": "Петропавловск-Камчатский",
    "4162": "Благовещенск", "4242": "Южно-Сахалинск",
    "39151": "Биробиджан", "4232": "Уссурийск", "4236": "Находка",
    "3812": "Омск", "3822": "Томск", "3852": "Барнаул",
    "3902": "Абакан", "3952": "Иркутск", "3022": "Чита",
    "3012": "Улан-Удэ",
}

# ── Города → страна (крупные, для текстового сигнала) ───────────────────────
CITY_COUNTRY = {
    # Беларусь
    "минск": "Беларусь", "витебск": "Беларусь", "гомель": "Беларусь",
    "могил": "Беларусь", "брест": "Беларусь", "гродно": "Беларусь",
    "бобруйск": "Беларусь", "барановичи": "Беларусь", "борисов": "Беларусь",
    "пинск": "Беларусь", "орша": "Беларусь", "мозырь": "Беларусь",
    "солигорск": "Беларусь", "новополоцк": "Беларусь", "полоцк": "Беларусь",
    "лида": "Беларусь", "молодечно": "Беларусь", "жлобин": "Беларусь",
    # Россия
    "москва": "Россия", "москве": "Россия", "санкт-петербург": "Россия",
    "петербург": "Россия", "новосибирск": "Россия", "екатеринбург": "Россия",
    "казан": "Россия", "нижний новгород": "Россия", "челябинск": "Россия",
    "самар": "Россия", "омск": "Россия", "ростов": "Россия", "уф": "Россия",
    "красноярск": "Россия", "воронеж": "Россия", "перм": "Россия",
    "волгоград": "Россия", "краснодар": "Россия", "тюмень": "Россия",
    "саратов": "Россия", "тольятти": "Россия", "ижевск": "Россия",
    # Дальний Восток + Сибирь (зона «потеряли регион → угадаем Омск/Москву»)
    "хабаровск": "Россия", "владивосток": "Россия", "якутск": "Россия",
    "магадан": "Россия", "благовещенск": "Россия",
    "петропавловск-камчатский": "Россия", "южно-сахалинск": "Россия",
    "биробиджан": "Россия", "уссурийск": "Россия", "находка": "Россия",
    "томск": "Россия", "барнаул": "Россия", "абакан": "Россия",
    "иркутск": "Россия", "чита": "Россия", "улан-удэ": "Россия",
    "ярославл": "Россия", "тверь": "Россия", "тула": "Россия",
    "калининград": "Россия", "сочи": "Россия", "владимир": "Россия",
    # Республики и края (явные упоминания)
    "хабаровский край": "Россия", "приморский край": "Россия",
    "якутия": "Россия", "сахалинская область": "Россия",
    "амурская область": "Россия", "камчатский край": "Россия",
    "чукотский": "Россия",
    # Казахстан
    "алматы": "Казахстан", "астана": "Казахстан", "нур-султан": "Казахстан",
    "шымкент": "Казахстан", "караганда": "Казахстан",
    # Украина
    "киев": "Украина", "харьков": "Украина", "одесса": "Украина",
    "днепр": "Украина", "львов": "Украина",
}

# Вес сигналов (чем надёжнее — тем выше).
W_TLD = 3
W_PHONE = 4
W_LEGAL = 4
W_CURRENCY = 2
W_CITY = 2


def _region_from_phone(digits: str) -> Optional[Tuple[str, Optional[str]]]:
    """По нормализованным цифрам телефона → (страна, город|None)."""
    # +375 XX ... (Беларусь)
    if digits.startswith("375"):
        rest = digits[3:]
        city = None
        # код города — 2-4 цифры после 375
        for length in (4, 3, 2):
            code = rest[:length]
            if code in BY_CITY_CODES:
                city = BY_CITY_CODES[code]
                break
        return "Беларусь", city
    if digits.startswith("380"):
        return "Украина", None
    if digits.startswith("998"):
        return "Узбекистан", None
    if digits.startswith(("7", "8")) and len(digits) >= 11:
        # +7 — Россия или Казахстан. Казахстан: 77xx. Иначе Россия.
        if digits[:2] in ("77",) or digits[1:3] == "77":
            return "Казахстан", None
        # +7 РФ-городской код → конкретный город. Перебираем от длинных
        # к коротким: 4-значные (4212 Хабаровск) важнее 3-значных (812 СПб),
        # чтобы для номера +7 4212 ... не сматчилось «421», которого нет.
        rest = digits[1:] if digits[0] == "7" else digits[1:]
        for length in (5, 4, 3):
            code = rest[:length]
            if code in RU_CITY_CODES:
                return "Россия", RU_CITY_CODES[code]
        return "Россия", None
    return None


def _extract_signals(url: str, text: str) -> list[tuple[str, str, int, Optional[str]]]:
    """Возвращает список сигналов: (тип, страна, вес, город|None)."""
    signals: list[tuple[str, str, int, Optional[str]]] = []
    low = text.lower()

    # 1. TLD
    ext = tldextract.extract(url)
    tld = (ext.suffix or "").split(".")[-1].lower()
    if tld in TLD_COUNTRY:
        signals.append(("tld", TLD_COUNTRY[tld], W_TLD, None))

    # 2. Телефоны
    for m in re.findall(r"\+?\d[\d\-\s()]{8,}\d", text):
        digits = re.sub(r"\D", "", m)
        if len(digits) < 10:
            continue
        res = _region_from_phone(digits)
        if res:
            signals.append(("phone", res[0], W_PHONE, res[1]))

    # 3. Реквизиты: УНП (Беларусь) vs ИНН/ОГРН (Россия)
    if re.search(r"\bУНП\b", text, re.IGNORECASE):
        signals.append(("legal", "Беларусь", W_LEGAL, None))
    if re.search(r"\b(ИНН|ОГРН|ОГРНИП|КПП)\b", text, re.IGNORECASE):
        signals.append(("legal", "Россия", W_LEGAL, None))
    if re.search(r"\b(БИН|ИИН)\b", text):  # Казахстан
        signals.append(("legal", "Казахстан", W_LEGAL, None))

    # 4. Валюта
    if re.search(r"\bBYN\b|бел\.?\s?руб|белорусских руб", low):
        signals.append(("currency", "Беларусь", W_CURRENCY, None))
    if "₸" in text or "тенге" in low:
        signals.append(("currency", "Казахстан", W_CURRENCY, None))
    if "₴" in text or "грн" in low or "гривен" in low:
        signals.append(("currency", "Украина", W_CURRENCY, None))

    # 5. Города — ТЗ catcore-5-globalnyh-fiksov Фикс 5 v2: stem-match
    # для русских словоформ + приоритет длинного.
    #
    # Корень: ключи в CITY_COUNTRY в именительном падеже («хабаровск»,
    # «хабаровский край»). В тексте они почти всегда в других формах:
    # «в Хабаровск-ом кра-е». Простой `\bхабаровский край\w*` не сматчит
    # из-за словоформы «хабаровск**ом**».
    #
    # Решение: каждое слово ключа превращается в стем (первые N букв,
    # 5–6) + `\w*` хвост → сматчит любую словоформу. «хабаровский край»
    # → паттерн `\bхабаровск\w* кра\w*` ловит «Хабаровском крае».
    #
    # Сортировка по числу слов в ключе (DESC) + по длине → составные
    # ключи побеждают одиночные. consumed_spans защищает от double-count.
    def _stem(word: str, default_len: int = 6) -> str:
        """Стем-основа для матча словоформ. ВАЖНО (Правка 3): даже короткие
        слова получают усечение, чтобы «край» матчил «крае», «краю».
        Берём первые min(len, 4) букв для слов ≤4 (но не короче 3),
        и первые 6 для длинных. Хвост \w* добавляется снаружи.
          «край» (4)        → «кра»   → «кра\w*» ловит край/крае/краю/края
          «хабаровский» (11)→ «хабаро»→ «хабаро\w*»
          «уфа» (3)         → «уфа»   (3 буквы, целиком, чтобы не ловить «уфолог»)
        """
        n = len(word)
        if n <= 3:
            return re.escape(word)
        if n <= 4:
            return re.escape(word[:3])
        return re.escape(word[:default_len])

    def _build_pattern(key: str) -> re.Pattern:
        # Каждое слово → стем-основа + \w* (любая словоформа).
        # «хабаровский край» → r"\bхабаро\w*\s+кра\w*" ловит «Хабаровском крае».
        words = key.split()
        parts = [_stem(w) + r"\w*" for w in words]
        return re.compile(r"\b" + r"\s+".join(parts), re.UNICODE)

    # Сортировка: сначала ключи с большим числом слов (составные), внутри —
    # по длине строки. «хабаровский край» (2 слова) > «хабаровск» (1).
    sorted_keys = sorted(
        CITY_COUNTRY.keys(),
        key=lambda k: (len(k.split()), len(k)),
        reverse=True,
    )
    consumed_spans: list[tuple[int, int]] = []
    for city_key in sorted_keys:
        try:
            pat = _build_pattern(city_key)
        except re.error:
            continue
        # Специфичность: составной ключ («хабаровский край», 2 слова) весит
        # больше одиночного («хабаровск», 1 слово). При равном числе вхождений
        # это даёт победу более специфичному региону. Механика глобальная:
        # работает для всех пар город/край (Ростов/Ростовская и т.д.).
        key_weight = W_CITY + (len(city_key.split()) - 1)
        for m in pat.finditer(low):
            span = (m.start(), m.end())
            # Защита от double-count: если этот span уже накрыт более длинным.
            if any(s[0] <= span[0] < s[1] for s in consumed_spans):
                continue
            consumed_spans.append(span)
            country = CITY_COUNTRY[city_key]
            display = " ".join(w.capitalize() for w in city_key.split())
            signals.append(("city", country, key_weight, display))

    return signals


def count_distinct_cities(text: str) -> int:
    """Сколько РАЗНЫХ городов/регионов из газеттира упомянуто в тексте.

    Используется для детекции агрегаторов/каталогов: одна локальная компания
    привязана к 1-2 городам, а каталог (domik.travel, 101hotels, агрегатор
    бухгалтерий и т.п.) перечисляет десятки. Сигнал нишево-независимый —
    работает для любой категории и страны. Переиспользует тот же stem-матч,
    что и определение региона (словоформы, защита от double-count).
    """
    if not text:
        return 0
    try:
        signals = _extract_signals("", text)
    except Exception:
        return 0
    cities = {s[3] for s in signals if s[0] == "city" and s[3]}
    return len(cities)


def _aggregate(signals: list) -> dict:
    """Считает голоса по странам, выбирает страну и город."""
    if not signals:
        return {"country": "unknown", "city": None, "confidence": "low", "signals": []}

    votes: Counter = Counter()
    city_votes: Counter = Counter()
    strong_present = False
    for stype, country, weight, city in signals:
        votes[country] += weight
        if stype in ("tld", "phone", "legal"):
            strong_present = True
        if city:
            city_votes[city] += weight

    best_country, best_score = votes.most_common(1)[0]
    # Уверенность: высокая, если есть сильный сигнал и нет сопоставимого конкурента.
    runner_up = votes.most_common(2)
    second_score = runner_up[1][1] if len(runner_up) > 1 else 0
    confidence = "high" if (strong_present and best_score >= second_score * 2) else (
        "medium" if strong_present else "low"
    )

    city = city_votes.most_common(1)[0][0] if city_votes else None
    return {
        "country": best_country,
        "city": city,
        "confidence": confidence,
        "signals": [{"type": s[0], "country": s[1], "city": s[3]} for s in signals],
    }


async def detect_region(url: str) -> Tuple[dict, str]:
    """Определяет регион бизнеса по сайту.

    Возвращает (region_info, page_text):
      region_info = {country, city, confidence, region (строка для pipeline), signals}
      page_text — сырой текст главной (переиспользуется для определения ниши).
    """
    page_text = ""
    if url and url.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(
                timeout=15.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
            ) as client:
                resp = await client.get(url)
                if resp.status_code < 400 and resp.text:
                    # Грубо снимаем теги — нам нужен только текст для сигналов.
                    raw = resp.text
                    page_text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
                    page_text = re.sub(r"<[^>]+>", " ", page_text)
                    page_text = re.sub(r"\s+", " ", page_text)[:20000]
        except Exception as exc:
            logger.warning("detect_region_fetch_error", url=url, error=str(exc))

    signals = _extract_signals(url, page_text)
    info = _aggregate(signals)

    # Строка региона для остального pipeline: «Город, Страна» или «Страна».
    if info["country"] == "unknown":
        info["region"] = ""  # дальше LLM/клиент уточняют, дефолт Россия запрещён
    elif info["city"]:
        info["region"] = f"{info['city']}, {info['country']}"
    else:
        info["region"] = info["country"]

    logger.info(
        "region_detected",
        url=url,
        country=info["country"],
        city=info["city"],
        confidence=info["confidence"],
    )
    return info, page_text
