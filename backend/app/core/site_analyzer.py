"""Анализ главной страницы сайта клиента и конкурентов.

Этап 2.1 ТЗ. Парсим один URL, возвращаем чек-лист готовности к GEO-цитированию.
Это источник данных для страницы 6 PDF («что есть у лидера, чего нет у вас»).

Принципы:
- Только главная страница + три служебных URL (/robots.txt, /sitemap.xml, /llms.txt).
- Все запросы с таймаутом, исключения ловим — анализ конкретного сайта может
  упасть, pipeline это переживёт (`fetched: False` в результате).
- Не используем headless browser — парсим только то, что отдаёт HTTP без JS.
  Для большинства корпоративных сайтов этого достаточно; SPA-сайты помечаем
  пониженным `content_length_estimate`.
"""

import asyncio
import json
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.utils.logger import get_logger

logger = get_logger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; CatCoreAIVisibilityBot/1.0; "
    "+https://catcore.ru) AppleWebKit/537.36"
)

# Слова — маркеры E-E-A-T сигналов на странице (русский + английский).
EEAT_SIGNALS = [
    r"\bлет\s+(на\s+рынке|опыт[аы]|работы)\b",
    r"\bстаж\b",
    r"\bсертификат(ы|ом|ах)?\b",
    r"\bлиценз(ия|ии|ирован)\b",
    r"\bопыт\b",
    r"\bкоманд[аы]\b",
    r"\bэксперт(ы|ов)?\b",
    r"\bосновате[лр](ь|и|я)\b",
    r"\bпрофесси(оналы?|ональ)\b",
    r"\baward\b",
    r"\bcertified?\b",
    r"\byears?\s+of\s+experience\b",
]
EEAT_RE = re.compile("|".join(EEAT_SIGNALS), re.IGNORECASE)

# Пути типичных страниц "О нас" и "Контакты"
ABOUT_PATHS = ["/about", "/o-nas", "/about-us", "/o-kompanii", "/company"]
CONTACT_PATHS = ["/contact", "/contacts", "/kontakty"]

# Боты ИИ-ассистентов, которых проверяем в robots.txt
AI_BOTS = ["GPTBot", "ClaudeBot", "Google-Extended", "PerplexityBot", "anthropic-ai", "YandexBot"]


async def _fetch(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    """GET с проглатыванием ошибок (для опциональных URL вроде /llms.txt)."""
    try:
        return await client.get(url, follow_redirects=True)
    except Exception:
        return None


async def _check_exists(client: httpx.AsyncClient, base: str, path: str) -> tuple[bool, Optional[str]]:
    """HEAD/GET — есть ли файл по пути. Возвращает (exists, body_or_None).

    Body возвращаем для robots.txt — нужно разобрать содержимое.
    """
    target = urljoin(base, path)
    try:
        resp = await client.get(target, follow_redirects=True)
        if resp.status_code == 200 and resp.text:
            return True, resp.text
    except Exception:
        pass
    return False, None


def _robots_allows_ai(robots_text: str) -> dict[str, bool]:
    """Проверяет, разрешает ли robots.txt доступ ИИ-ботам.

    Возвращает dict {bot_name: allowed_bool}. Простая интерпретация:
    ищем User-agent: <bot> и проверяем, есть ли явный Disallow: /.
    """
    out: dict[str, bool] = {}
    text = robots_text.lower()
    for bot in AI_BOTS:
        bot_l = bot.lower()
        # Находим блок для этого бота
        # Простая эвристика: если есть строка "user-agent: <bot>" и в её блоке "disallow: /"
        idx = text.find(f"user-agent: {bot_l}")
        if idx == -1:
            # Не упомянут явно — попадает под общее правило (* default allow)
            out[bot] = True
            continue
        # Берём всё до следующей пустой строки или следующего User-agent
        block_end_candidates = [
            text.find("\n\n", idx),
            text.find("\nuser-agent:", idx + 12),
        ]
        block_end_candidates = [c for c in block_end_candidates if c > 0]
        block_end = min(block_end_candidates) if block_end_candidates else len(text)
        block = text[idx:block_end]
        disallowed = bool(re.search(r"disallow:\s*/\s*$|disallow:\s*/\n", block))
        out[bot] = not disallowed
    return out


def _detect_schema_org(soup: BeautifulSoup) -> dict[str, bool]:
    """Ищет JSON-LD блоки и возвращает {FAQPage, Organization, BreadcrumbList}."""
    out = {"FAQPage": False, "Organization": False, "BreadcrumbList": False}
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw = tag.string or tag.get_text() or ""
            if not raw.strip():
                continue
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        _walk_schema(data, out)
    return out


def _walk_schema(node: Any, out: dict[str, bool]) -> None:
    """Рекурсивный обход @type."""
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str) and t in out:
            out[t] = True
        elif isinstance(t, list):
            for item in t:
                if isinstance(item, str) and item in out:
                    out[item] = True
        for v in node.values():
            _walk_schema(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_schema(item, out)


# Юр.название в кавычках — строго требуем ЗАКРЫВАЮЩУЮ кавычку, ограничиваем
# содержимое 40 символов без вложенных кавычек. Это режет «...ООО "Бухг» (хвост
# чужого текста без закрытия) и «...ООО "Время учёта" УНП 391824980 р...»
# (захват соседних слов через простую жадную маску).
_LEGAL_NAME_QUOTED_RE = re.compile(
    r'(ООО|ОДО|ЗАО|ОАО|ЧУП|ЧТУП|УП|ПАО|АО)\s*'
    r'(?:«([^«»\n\r]{2,40})»|"([^"\n\r]{2,40})"|“([^”\n\r]{2,40})”)',
    re.UNICODE,
)
# Резервный вариант: «ООО SingleWord» (одно слово без кавычек) — например,
# «ООО АудитПлюс». Жадности не даём — ровно одно слово.
_LEGAL_NAME_BARE_RE = re.compile(
    r'(ООО|ОДО|ЗАО|ОАО|ЧУП|ЧТУП|УП|ПАО|АО)\s+'
    r'([А-ЯЁA-Z][а-яёa-zA-Z0-9\-]{2,30})\b',
    re.UNICODE,
)
# ИП — отдельный случай, форма «ИП Фамилия И.О.» (а плейсхолдеры режутся
# is_placeholder_name). Допустим, до 3 слов после «ИП».
_LEGAL_NAME_IP_RE = re.compile(
    r'(ИП)\s+([А-ЯЁ][а-яё]{2,30}(?:\s+[А-ЯЁ]\.?\s*[А-ЯЁ]\.?)?)',
    re.UNICODE,
)

# Старое имя сохраняем для совместимости (если где-то ссылаются).
_LEGAL_NAME_RE = _LEGAL_NAME_QUOTED_RE

# Шаблоны плейсхолдеров от ИИ-галлюцинаций: «ИП Иванов И.И.», «ИП Петрова О.В.»
# — эта структура почти всегда выдуманная (учебный пример), реальные имена ИП
# обычно с полным отчеством или нетипичной фамилией. Выкидываем.
_PLACEHOLDER_IP_RE = re.compile(
    r'^\s*(ип|чтуп|унп|унн)\s+[а-яё]+(?:а|ова|ев|ева|ин|ина|ский|ская)\s+[а-яё]\.\s*[а-яё]\.\s*$',
    re.IGNORECASE | re.UNICODE,
)

# Template literals из шаблонизаторов сайта, которые не отрендерились на проде:
#   $[properties.brand.title]      ← Bitrix24/1С-Битрикс property-syntax
#   ${product.name}                ← JS template
#   {{ brand }}                    ← Mustache/Vue/Angular
#   <%= name %>                    ← ERB / EJS
# Реальный сайт со сломанным шаблоном кладёт такую строку в og:site_name
# или в <title>, мы выгребаем её как «бренд», и в отчёт попадает мусор.
_TEMPLATE_LITERAL_RE = re.compile(
    r'(\$[\[\{][^\]\}]+[\]\}])|(\{\{\s*[^}]+\s*\}\})|(<%[^%]+%>)',
)

# Мусорные хвосты в org_name, когда экстрактор зацепил кусок меню/футера.
_NAME_GARBAGE_TAILS = [
    "главная", "о компании", "о нас", "контакты", "услуги", "цены", "прайс",
    "menu", "home", "about", "contacts", "новости", "блог",
]


def clean_org_name(name: Optional[str]) -> Optional[str]:
    """Чистит извлечённое название от мусора: лишних символов, хвостов меню,
    дублей, технических идентификаторов (УНП/ИНН/ОГРН). None — если после
    чистки осталась пустота или явно мусор (CSS-классы, файлы).
    """
    if not name:
        return None
    s = re.sub(r"\s+", " ", name).strip(" \t\r\n.,;:|/\\—–-«»\"'")
    if not s:
        return None

    # Отсев CSS-классов и техимён файлов (alt вида «logo_main», «site-logo», «img_logo»).
    s_low_full = s.lower()
    if re.match(r'^(logo|лого|site|img|icon|header|footer|banner|brand|nav|main)[_\- ]', s_low_full):
        return None
    if re.fullmatch(r'[a-z][a-z0-9_\-]{2,20}', s_low_full) and ("_" in s_low_full or "-" in s_low_full):
        # «logo_main», «site-logo», «img_top» — типичный CSS, не бренд
        return None
    # Отсев имени, которое выглядит как доменное имя («buhvitebsk.by», «pravoved.ru»).
    # Реальный бренд так почти никогда не записывают (если хотят показать домен —
    # обычно через "Имя | example.com"). Кириллица в имени → не считаем доменом
    # (например, «Правовед.RU» сохраним — режется уже регион-проверкой).
    if re.fullmatch(r'[a-z][a-z0-9\-]{1,40}\.[a-z]{2,8}', s_low_full):
        return None

    # Срезаем хвост с УНП/ИНН/ОГРН и подобными идентификаторами
    s = re.split(r'\b(УНП|ИНН|ОГРН|ОКПО|БИК|КПП|УНН)\b', s, maxsplit=1)[0].strip()

    # Обрезаем по первому хвосту меню («ООО Аудит-Плюс Главная О ком...» → «ООО Аудит-Плюс»)
    s_low = s.lower()
    cut_at = len(s)
    for tail in _NAME_GARBAGE_TAILS:
        idx = s_low.find(tail)
        if idx > 0 and (s_low[idx - 1] in " \t|/—–-«»\"'"):
            cut_at = min(cut_at, idx)
    # Дополнительно режем по типичным фразам-склейкам шапки/футера
    for stop_phrase in (" мы находимся", " создание сайт", " ©", " все права"):
        idx = s_low.find(stop_phrase)
        if idx > 0:
            cut_at = min(cut_at, idx)
    s = s[:cut_at].strip(" \t\r\n.,;:|/\\—–-«»\"'")

    # Жёсткая обрезка длины (заголовок страницы целиком — это уже не имя).
    if len(s) > 50:
        s = s[:50].strip()
    if not s or len(s) < 2:
        return None
    # Удаляем дубль типа «ООО Аудит-Плюс ООО Аудит-Плюс» (часто от og:title)
    half = len(s) // 2
    if s[:half].strip() == s[half:].strip(" ") and half > 4:
        s = s[:half].strip()
    # Финально: имя из >5 слов почти всегда мусор (даже после чисток).
    if len(s.split()) > 5:
        return None
    return s or None


_IMPERATIVE_VERBS = (
    "отдыхай", "приезжай", "выбирай", "заказывай", "забронируй",
    "насладит", "посети", "купи", "узнай", "получи", "оставь",
    "звони", "обратись", "доверь", "попробуй", "смотри",
    "rest", "enjoy", "book", "choose", "discover", "explore",
)


def looks_like_slogan(name: str) -> bool:
    """True если строка похожа на слоган/призыв, а не на название компании.

    Примеры мусора, который раньше прорывался в Block A:
      - «Отдых в гармонии с природой!»  (восклицание + общие слова)
      - «Приезжайте к нам отдохнуть»     (императив + предлоги)
      - «Best place to stay in Khabarovsk» (длинная фраза)

    Логика:
      - Содержит «!» или «?» → почти всегда слоган.
      - >5 слов → не имя собственное.
      - Длина >50 символов → не имя.
      - Начинается с глагола в личной форме (отдыхайте, приезжайте, и т.п.).
    """
    if not name:
        return False
    s = name.strip()
    if "!" in s or "?" in s:
        return True
    if len(s) > 50:
        return True
    words = s.split()
    if len(words) > 5:
        return True
    first = words[0].lower().strip("«»\"'.,;:-—")
    for verb in _IMPERATIVE_VERBS:
        if first.startswith(verb):
            return True
    return False


def is_placeholder_name(name: str) -> bool:
    """True для шаблонов ИИ-галлюцинаций и неотрендеренных JSON-LD/og плейсхолдеров.

    Включает:
    - «ИП Иванов И.И.» (галлюцинация LLM)
    - «$[properties.brand.title]» (нерендеренный Bitrix property)
    - «{{ brand }}», «${name}», «<%= title %>» (Mustache/Vue/JS/EJS шаблоны)

    НЕ включает короткие имена: реальные бренды могут быть длиной 2-3 символа
    в любом регистре («Bat» (bat.by — реальный белорусский АКБ-магазин), «A1»,
    «M2», «МТС»). Был кейс — фильтр short-Mixed-case отсёк bat.by, который сам
    клиент ввёл как конкурента. Откат: коротких не отсекаем.
    """
    if not name:
        return True
    s = name.strip()
    if _PLACEHOLDER_IP_RE.match(s):
        return True
    if _TEMPLATE_LITERAL_RE.search(s):
        return True
    return False

# Родовые/служебные слова. «Generic» — это когда ВСЕ значимые слова отсюда
# (чистая категория «Бухгалтерские услуги»). Если есть хоть один собственный
# токен («Время», «ЛюксБаланс») — это бренд, НЕ generic.
_GENERIC_WORDS = {
    "услуги", "услуга", "услуг", "бухгалтерские", "бухгалтерия", "бухгалтерский",
    "бухгалтерское", "бухучёт", "бухучет", "аутсорсинг", "аутсорс", "аудит",
    "аудиторские", "консалтинг", "консалтинговые", "сопровождение", "учёт", "учет",
    "налоговый", "налоговые", "налоги", "налогообложение", "решение", "решения",
    # Все формы «компания/фирма/центр» — на единственном виде ловились только ед.ч.,
    # из-за этого «Компании» (мн.) проскакивал как валидный «бренд».
    "компания", "компании", "компанию", "компанией", "фирма", "фирмы",
    "организация", "организации", "центр", "центра", "центры", "агентство",
    "агентства", "бюро", "группа", "группы", "сервис", "сервисы", "обслуживание",
    "комплексное", "комплексное", "для", "бизнеса", "бизнес", "и", "в",
    "на", "под", "ключ", "цены", "цена", "недорого", "каталог", "магазин", "доставка",
    # города/регионы — это не бренд, а гео-привязка SEO-фразы
    "витебске", "витебск", "минске", "минск", "москве", "москва", "спб", "беларуси",
    "беларусь", "области", "области.",
    # Слишком общие категории-имена (ИИ называет их как «бренды» при общих
    # запросах — это маркетплейсы/категории, не нишевые конкуренты).
    "электроника", "техника", "интернет-магазин", "магазины", "товары",
    "век", "века", "веков",  # «21 Век», «Век» — частая SEO-обобщёнка
    "all", "best", "top", "lider", "лидер", "лидеры",
    # Госорганы/государственные ресурсы — НИКОГДА не конкуренты:
    "госуслуги", "госуслуга", "портал", "порталы", "ведомство", "ведомства",
    "министерство", "министерства", "налоговая", "налоговой",
    "государственный", "государственная", "государственное", "государственные",
    "пенсионный", "фонд", "фсс", "пфр",
    # Категории в мн.ч. (туризм/отдых/гостиничный бизнес). Реальный бренд
    # всегда имеет уникальное слово — здесь только КАТЕГОРИИ как таковые,
    # которые ИИ называет вместо конкретных компаний («лучшие агроусадьбы…»).
    "агроусадьба", "агроусадьбы", "агроэкоусадьба", "агроэкоусадьбы",
    "турбаза", "турбазы", "база", "базы", "комплекс", "комплексы",
    "гостиница", "гостиницы", "отель", "отели", "хостел", "хостелы",
    "пансионат", "пансионаты", "санаторий", "санатории",
    "кемпинг", "кемпинги", "глэмпинг", "глэмпинги",
    "домик", "домики", "коттедж", "коттеджи", "апартамент", "апартаменты",
    "хаус", "гостевой", "усадьба", "усадьбы",
    "отдых", "отдыха", "туризм", "путешествия",
}

# Имена-числа («21», «100», «777»), номера в чистом виде — не бренды.
# «21 Век» отсеять отдельно через комбинацию: число + generic-слово «Век»
# → оба токена generic → имя generic. Уже работает через _GENERIC_WORDS.
_DIGIT_ONLY_RE = re.compile(r'^\d+(?:[\s\-./]\d+)*$')


def looks_generic_name(name: str) -> bool:
    """True, если «название» — родовое описание (категория), а не бренд.

    Логика (Итерация-3): generic ⇔ среди слов НЕТ ни одного собственного токена
    (всё — категория/гео/служебное). «Бухгалтерские услуги» → True; «Время Учёта»,
    «ЛюксБаланс», «Бухгалтерские технологии» → False. Лучше пропустить лишнее,
    чем выкинуть реальный бренд (recall важнее точности на этом шаге).
    """
    s = (name or "").strip()
    if not s:
        return True
    # Юр.форма в начале — это уже конкретное название.
    if re.match(r"^(ооо|одо|зао|оао|чуп|чтуп|уп|ип|пао|ао)\b", s.lower()):
        return False
    tokens = [t.strip("«»\"'.,()-—:;").lower() for t in s.split()]
    meaningful = [t for t in tokens if t and t not in _GENERIC_WORDS and len(t) > 2]
    return len(meaningful) == 0


async def fetch_site_summary(url: str) -> Optional[dict]:
    """Лёгкий fetch сайта: реальное название организации + кусок видимого текста.

    Один HTTP-запрос (без analyze_site, без Playwright). Используется в:
    - подборе конкурентов (имя + категорийная проверка контента, Задача 4 Итер-3);
    - дешёвой верификации, что сайт кандидата реально про ту же услугу.
    Возвращает {"org_name": str|None, "text": str} или None если сайт не открылся.
    """
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru,en;q=0.9",
            },
        ) as client:
            resp = await client.get(url)
            if resp.status_code >= 400 or not resp.text:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            org_name = _extract_org_name(soup, url)
            for s in soup(["script", "style", "noscript"]):
                s.decompose()
            text = soup.get_text(" ", strip=True)[:8000].lower()
            return {"org_name": org_name, "text": text}
    except Exception as exc:
        logger.warning("fetch_site_summary_error", url=url, error=str(exc))
        return None


async def fetch_org_name(url: str) -> Optional[str]:
    """Только название (обёртка над fetch_site_summary)."""
    summary = await fetch_site_summary(url)
    return summary.get("org_name") if summary else None


def _org_name_from_jsonld(soup: BeautifulSoup) -> Optional[str]:
    """Достаёт name из schema.org Organization/LocalBusiness в JSON-LD."""
    org_types = {
        "Organization", "LocalBusiness", "Corporation", "ProfessionalService",
        "AccountingService", "Store", "LegalService", "NGO",
    }

    def _walk(node: Any) -> Optional[str]:
        if isinstance(node, dict):
            t = node.get("@type")
            types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
            if any(tt in org_types for tt in types):
                name = node.get("name") or node.get("legalName")
                if isinstance(name, str) and name.strip():
                    return name.strip()
            for v in node.values():
                found = _walk(v)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = _walk(item)
                if found:
                    return found
        return None

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw = tag.string or tag.get_text() or ""
            if not raw.strip():
                continue
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        name = _walk(data)
        if name:
            return name
    return None


def _extract_org_name(soup: BeautifulSoup, url: str) -> Optional[str]:
    """Реальное название компании по приоритету источников.

    1. schema.org Organization → name
    2. og:site_name
    3. logo alt / название в шапке
    4. юр.название из подвала (ООО «…», ЧУП «…»)
    НЕ используем <title> — там SEO-фразы. Каждый кандидат прогоняем
    через clean_org_name (Итер-3: режем хвосты меню, дубли, длину >50).
    Возвращает None, если ничего конкретного не нашли.
    """
    # 1. schema.org Organization
    name = clean_org_name(_org_name_from_jsonld(soup))
    if name and not looks_generic_name(name) and not is_placeholder_name(name):
        return name

    # 2. og:site_name
    og = soup.find("meta", attrs={"property": "og:site_name"})
    if og and og.get("content"):
        cand = clean_org_name(og["content"])
        if cand and not looks_generic_name(cand) and not is_placeholder_name(cand):
            return cand

    # 3. logo alt в шапке
    header = soup.find("header") or soup
    for img in header.find_all("img"):
        alt = (img.get("alt") or "").strip()
        cls = " ".join(img.get("class") or []).lower()
        if alt and ("logo" in cls or "logo" in (img.get("id") or "").lower() or "лого" in alt.lower() or "logo" in alt.lower()):
            raw = re.sub(r"(?i)\b(логотип|logo|лого)\b", "", alt).strip(" -—|_")
            # CSS-классоподобные хвосты («main», «top», «header», слова из 2-3 символов) — мусор.
            raw_low = raw.lower()
            if not raw or raw_low in ("main", "top", "bottom", "header", "footer", "site", "image", "icon"):
                continue
            cand = clean_org_name(raw)
            if cand and not looks_generic_name(cand) and not is_placeholder_name(cand):
                return cand

    # 4. юр.название из подвала — пробуем СТРОГИЕ регексы по очереди.
    # Только в кавычках («Время Учёта»), либо «ООО SingleWord», либо «ИП Фамилия И.О.».
    # Жадные/слабые паттерны убраны — раньше из-за них захватывался хвост «УНП ... р».
    footer = soup.find("footer")
    footer_text = (footer.get_text(" ", strip=True) if footer else soup.get_text(" ", strip=True))[:3000]
    for rx in (_LEGAL_NAME_QUOTED_RE, _LEGAL_NAME_BARE_RE, _LEGAL_NAME_IP_RE):
        m = rx.search(footer_text)
        if not m:
            continue
        # У _LEGAL_NAME_QUOTED_RE 4 группы (одна из 3 кавычек) — берём непустую.
        groups = [g for g in m.groups()[1:] if g]
        if not groups:
            continue
        # Без кавычек — clean_org_name всё равно режет «»» по краям, плюс
        # пользователь явно попросил их убрать («они не нужны»).
        legal_raw = f"{m.group(1)} {groups[0].strip()}"
        cand = clean_org_name(legal_raw)
        if cand and not is_placeholder_name(cand) and not looks_generic_name(cand):
            return cand

    return None


def country_from_site(url: str, text: str) -> str:
    """Итерация-3, Задача 4: страна сайта по жёстким сигналам (для проверки,
    что конкурент в той же стране, что и клиент). Используем TLD и токены
    городов/стран из region_detector.

    Возвращает «Беларусь»/«Россия»/... либо "" если сигналов нет.
    """
    try:
        import tldextract
        from app.core.region_detector import TLD_COUNTRY, CITY_COUNTRY
    except Exception:
        return ""

    # 1) TLD — самый сильный сигнал
    try:
        ext = tldextract.extract(url or "")
        tld = (ext.suffix or "").lower()
        if tld in TLD_COUNTRY:
            return TLD_COUNTRY[tld]
        # tld может быть составным (com.by → suffix='com.by') — берём «хвост».
        if "." in tld:
            last = tld.rsplit(".", 1)[-1]
            if last in TLD_COUNTRY:
                return TLD_COUNTRY[last]
    except Exception:
        pass

    # 2) Сигналы в тексте (страны и города)
    t = (text or "").lower()
    scores: dict[str, int] = {}
    explicit = [
        ("беларус", "Беларусь"), ("республика беларусь", "Беларусь"),
        ("россии", "Россия"), ("российской федерации", "Россия"),
        ("россия", "Россия"), ("украин", "Украина"),
        ("казахстан", "Казахстан"),
    ]
    for kw, country in explicit:
        if kw in t:
            scores[country] = scores.get(country, 0) + 3
    for city, country in CITY_COUNTRY.items():
        if city in t:
            scores[country] = scores.get(country, 0) + 1
    if scores:
        return max(scores.items(), key=lambda kv: kv[1])[0]
    return ""


def _detect_faq_block(soup: BeautifulSoup) -> bool:
    """Грубо: есть ли блок с вопросами-ответами без schema-разметки."""
    # Ищем секции/детали с вопросительными заголовками
    candidates = soup.find_all(["details", "summary"])
    if len(candidates) >= 3:
        return True
    # Заголовки с вопросительным знаком — типичный FAQ
    question_headings = 0
    for h in soup.find_all(["h2", "h3", "h4"]):
        text = (h.get_text() or "").strip()
        if "?" in text and 10 <= len(text) <= 150:
            question_headings += 1
    return question_headings >= 3


def _detect_structured_headings(soup: BeautifulSoup) -> bool:
    """Есть ли логичная иерархия h1 → h2 → h3."""
    h1 = len(soup.find_all("h1"))
    h2 = len(soup.find_all("h2"))
    h3 = len(soup.find_all("h3"))
    return h1 == 1 and h2 >= 2 and (h3 >= 1 or h2 >= 4)


def _content_length(soup: BeautifulSoup) -> int:
    """Грубая оценка количества слов в видимом контенте."""
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return len(text.split())


def _detect_language(soup: BeautifulSoup, fallback_text: str = "") -> str:
    """Определяет язык по <html lang> или эвристически."""
    html = soup.find("html")
    if html and html.get("lang"):
        lang = str(html.get("lang")).lower().split("-")[0]
        if lang in ("ru", "en", "be", "uk", "kk"):
            return lang
    # Эвристика по кириллице/латинице
    sample = fallback_text or soup.get_text()[:1000]
    cyrillic = sum(1 for c in sample if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in sample if "a" <= c.lower() <= "z")
    if cyrillic > latin * 2:
        return "ru"
    if latin > cyrillic * 2:
        return "en"
    return "unknown"


def _empty_result(url: str, reason: str) -> dict:
    return {
        "url": url,
        "fetched": False,
        "fetch_error": reason,
        "org_name": None,
        "has_llms_txt": False,
        "has_robots_txt": False,
        "has_sitemap": False,
        "has_faq_schema": False,
        "has_organization_schema": False,
        "has_breadcrumb_schema": False,
        "h1_count": 0,
        "structured_headings": False,
        "faq_block_present": False,
        "about_page_present": False,
        "contact_page_present": False,
        "expertise_signals": 0,
        "content_length_estimate": 0,
        "language": "unknown",
        "robots_allows_ai": {},
    }


async def analyze_site(url: str) -> dict:
    """Возвращает чек-лист готовности к GEO-цитированию для одного URL."""
    if not url or not url.startswith(("http://", "https://")):
        return _empty_result(url or "", "invalid_url")

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                # Близко к настоящему браузеру — часть сайтов режет «голые» запросы.
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru,en;q=0.9",
            },
        ) as client:
            # Главная страница — с ретраем (Задача 6.4: сайты иногда отвечают со 2-й попытки).
            main_resp = None
            for attempt in range(2):
                try:
                    main_resp = await client.get(url)
                    break
                except Exception as exc:
                    logger.warning("site_analyzer_fetch_attempt", url=url, attempt=attempt, error=str(exc))
                    if attempt == 1:
                        return _empty_result(url, f"fetch_error: {type(exc).__name__}")
                    await asyncio.sleep(1.0)

            if main_resp is None or main_resp.status_code >= 400 or not main_resp.text:
                code = main_resp.status_code if main_resp is not None else "none"
                return _empty_result(url, f"http_{code}")

            # Параллельные служебные запросы
            llms_task = _check_exists(client, base, "/llms.txt")
            robots_task = _check_exists(client, base, "/robots.txt")
            sitemap_task = _check_exists(client, base, "/sitemap.xml")
            about_tasks = [_check_exists(client, base, p) for p in ABOUT_PATHS[:3]]
            contact_tasks = [_check_exists(client, base, p) for p in CONTACT_PATHS[:3]]

            (
                (has_llms, _),
                (has_robots, robots_text),
                (has_sitemap, _),
                about_results,
                contact_results,
            ) = await asyncio.gather(
                llms_task,
                robots_task,
                sitemap_task,
                asyncio.gather(*about_tasks, return_exceptions=True),
                asyncio.gather(*contact_tasks, return_exceptions=True),
            )

        about_page_present = any(
            isinstance(r, tuple) and r[0] for r in about_results
        )
        contact_page_present = any(
            isinstance(r, tuple) and r[0] for r in contact_results
        )

        # Парсим главную
        soup = BeautifulSoup(main_resp.text, "html.parser")
        schema = _detect_schema_org(soup)
        h1_count = len(soup.find_all("h1"))
        text_sample = soup.get_text(" ", strip=True)[:5000]

        return {
            "url": url,
            "fetched": True,
            "fetch_error": None,
            "org_name": _extract_org_name(soup, url),
            "has_llms_txt": has_llms,
            "has_robots_txt": has_robots,
            "robots_allows_ai": _robots_allows_ai(robots_text) if robots_text else {},
            "has_sitemap": has_sitemap,
            "has_faq_schema": schema["FAQPage"],
            "has_organization_schema": schema["Organization"],
            "has_breadcrumb_schema": schema["BreadcrumbList"],
            "h1_count": h1_count,
            "structured_headings": _detect_structured_headings(soup),
            "faq_block_present": _detect_faq_block(soup),
            "about_page_present": about_page_present,
            "contact_page_present": contact_page_present,
            "expertise_signals": len(EEAT_RE.findall(text_sample)),
            "content_length_estimate": _content_length(soup),
            "language": _detect_language(soup, text_sample),
        }
    except Exception as exc:
        logger.error(
            "site_analyzer_unexpected_error",
            url=url,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return _empty_result(url, f"unexpected: {type(exc).__name__}")
