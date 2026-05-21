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
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            # Главная страница
            try:
                main_resp = await client.get(url)
            except Exception as exc:
                logger.warning("site_analyzer_fetch_main_error", url=url, error=str(exc))
                return _empty_result(url, f"fetch_error: {type(exc).__name__}")

            if main_resp.status_code >= 400 or not main_resp.text:
                return _empty_result(url, f"http_{main_resp.status_code}")

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
