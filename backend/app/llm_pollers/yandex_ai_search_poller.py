import base64
import re
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from app.llm_pollers.base import BasePoller, RateLimitError


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _decode_base64_html(b64: str) -> str:
    """base64 → HTML → plain text. Используется и для Google AI Overview
    (<answer>), и для Яндекс-Нейро (<content>) — обе обёртки одинаковые."""
    try:
        html_bytes = base64.b64decode(b64)
        html = html_bytes.decode("utf-8", errors="ignore")
    except Exception:
        return ""
    html = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&mdash;", "—")
        .replace("&amp;", "&")
        .replace("&laquo;", "«")
        .replace("&raquo;", "»")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    return _WS_RE.sub(" ", text).strip()


_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_URL_INLINE_RE = re.compile(r'https?://[\w\-.]+(?:/[^\s,)\]\'"]*)?', re.IGNORECASE)


class YandexAISearchPoller(BasePoller):
    """Парсит выдачу Яндекса с AI-блоком (Нейро) через XMLRiver SERP API.

    Источник называется честно — это не "Алиса" (прямого API у голосового
    ассистента нет), а Яндекс-поиск с AI-сгенерированным блоком. Эта же выдача
    лежит в основе ответов Алисы — поэтому данные близки к тому, что услышит
    пользователь Алисы, хотя и не идентичны.

    Алиас AlisaPoller сохранён в __init__.py для обратной совместимости
    импортов в pipeline.
    """

    name = "yandex_ai_search"
    display_name = "Яндекс-поиск с AI-блоком"
    model = "yandex-ai-search"

    def __init__(self, cache, config):
        super().__init__(cache, config)
        # Citations per prompt — ссылки-источники, которые Алиса упоминает
        # в ответе. Извлекаются из base64-HTML <content> блока: либо как
        # <a href="..."> теги, либо как plain-text «1. domain.tld» в списке
        # источников. Pipeline забирает через consume_citations().
        self._citations: dict[str, list[str]] = {}

    def consume_citations(self) -> dict[str, list[str]]:
        out = dict(self._citations)
        self._citations.clear()
        return out

    def _extract_citations_from_html(self, html: str) -> list[str]:
        """Из HTML Алисы: сначала <a href>, потом голые URL в тексте.
        Дедуп по домену, нормализуем."""
        urls: list[str] = []
        seen: set[str] = set()
        for m in _HREF_RE.findall(html or ""):
            u = m.strip()
            if u.startswith("//"):
                u = "https:" + u
            if u.startswith(("http://", "https://")) and u not in seen:
                seen.add(u)
                urls.append(u)
        # plain-text «alice.yandex.ru», «habr.com» — после strip-tags
        text_only = re.sub(r"<[^>]+>", " ", html or "")
        for m in _URL_INLINE_RE.findall(text_only):
            u = m.strip().rstrip(".,;:)\"'")
            if u not in seen:
                seen.add(u)
                urls.append(u)
        return urls[:30]

    async def _query_raw(self, prompt: str, region: str = "") -> str:
        # КРИТИЧНЫЙ ФИКС 31.05.26: Яндекс-Нейро для БР-локали (lr=149) AI-блок
        # НЕ возвращает вообще — на любых запросах. Подтверждено curl-серией:
        #   lr=149 + neuro=1 + «аккумуляторы минск»       → нет <ai>
        #   lr=149 + neuro=1 + «аккумуляторы минск купить» → нет <ai>
        #   lr=225 + neuro=1 + «аккумуляторы минск»       → <ai><content>16KB</content>
        # Это ограничение Яндекса для белорусской локали (Алиса в браузере
        # юзера-белоруса видит AI-блок ровно потому, что её Яндекс по умолчанию
        # идёт под РФ-локалью). Раньше для БР-клиента шли lr=149 → за всё
        # время ни одного реального ответа поллера.
        # Решение: для AI-блока всегда lr=РФ (225). AI поймёт из текста запроса
        # («минск», «в Беларуси»), о каком регионе речь, и упомянет локальных
        # игроков. Для органики (Block A SERP) lr_BY всё ещё корректен —
        # этот фикс касается ТОЛЬКО AI-блока, и только Яндекса.
        lr = self.config.XMLRIVER_REGION_RU
        # Правильный Yandex эндпоинт по документации XMLRiver — /search_yandex/xml,
        # не /search/xml (это Google). Раньше шёл на Google эндпоинт с lr-кодами
        # для Yandex — отсюда часть пустых ответов.
        url = "https://xmlriver.com/search_yandex/xml"
        # ВАЖНО (31.05.26): у /search_yandex/xml связки country/loc нет — гео
        # задаётся одним lr. Параметр neuro=1 включает запрос AI-блока (Нейро),
        # но текст приходит, только если в кабинете XMLRiver включена доплата
        # за расширенный AI-блок Яндекса. Иначе в ответе только маркер
        # <ai><item><content/></item></ai> без текста.
        params = {
            "user": self.config.XMLRIVER_USER,
            "key": self.config.XMLRIVER_KEY,
            "query": prompt,
            "lr": lr,
            "neuro": "1",
        }

        # Симметричный фикс к Google AI Overview: XMLRiver на /search/xml
        # без User-Agent/Accept-Language режет русские запросы в антибот
        # (error 15). /search_yandex/xml сейчас работает и без заголовков,
        # но добавляем превентивно — стоит копейки, защищает от того же
        # подвоха на их стороне.
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/xml,application/xml,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
            response = await client.get(url, params=params)
            if response.status_code == 429:
                raise RateLimitError("XMLRiver rate limit")
            response.raise_for_status()

            # Сбрасываем предыдущие citations этого вызова и парсим Нейро.
            self._last_citations = []
            neuro_text = self._extract_neuro_block(response.text)
            if neuro_text:
                # Привязываем citations к промпту для pipeline'а.
                if self._last_citations:
                    self._citations[prompt] = list(self._last_citations)
                return neuro_text

            organic = self._extract_top_organic(response.text, count=3)
            if organic:
                summary = " | ".join(
                    [f"{r['title']}: {r['snippet']}" for r in organic]
                )
                return f"[AI-ответ недоступен для запроса] Топ-3 Яндекс: {summary}"

            return "[AI-блок в Яндекс-выдаче недоступен для этого запроса]"

    def _extract_neuro_block(self, xml_text: str) -> Optional[str]:
        """Извлекает текст Яндекс-Нейро из ответа XMLRiver.

        ФИКС 31.05.26 (часть 1): реальный тег у XMLRiver — <ai>, не <neuro>.
        Структура (подтверждена curl-ом lr=225 + neuro=1 + платная галочка):
            <ai>
              <item>
                <type>center</type>
                <position>1</position>
                <content>base64(HTML интерфейса Алисы/Поиска)</content>
              </item>
            </ai>
        Старый код искал теги <neuro>/<neural-answer>/<ai-answer> — таких в
        ответе нет, поэтому 100% запросов отдавали None и падали в fallback
        на органику. Оставляем старые теги как fallback.

        ФИКС 31.05.26 (часть 2): <content> приходит base64-encoded HTML,
        точно так же, как <answer> у Google AI Overview. Без декодирования
        в pipeline попадёт base64-строка, и анализ упоминаний не сработает.

        ВАЖНО: на запросах БР-локали (lr=149) и части запросов РФ
        <ai>-блок отсутствует — Yandex просто не показал AI-ответ. В таком
        случае возвращаем None → fallback на органику.
        """
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None

        # Новый формат: <ai><item><content>base64(HTML)</content></item></ai>
        for item in root.findall(".//ai/item"):
            content_el = item.find("content")
            raw = (content_el.text or "").strip() if content_el is not None else ""
            if raw:
                # Декодируем base64 → HTML отдельно, чтобы достать citations.
                try:
                    import base64 as _b64
                    html = _b64.b64decode(raw).decode("utf-8", errors="ignore")
                except Exception:
                    html = ""
                # Citations извлекаем из HTML до strip-tags — там <a href>.
                if html:
                    cits = self._extract_citations_from_html(html)
                    if cits:
                        # Сохраним под текущий промпт (parent doesn't have it,
                        # вызывающий код сделает self._citations[prompt] = ...).
                        # Тут возвращаем «marker» через атрибут last_citations:
                        self._last_citations = cits
                decoded = _decode_base64_html(raw)
                if decoded:
                    return decoded

        # Fallback на legacy-теги (если XMLRiver когда-нибудь вернёт старую структуру)
        for tag in ("neuro", "neural-answer", "ai-answer"):
            el = root.find(f".//{tag}")
            if el is not None and (el.text or "").strip():
                return el.text.strip()
        return None

    def _extract_top_organic(self, xml_text: str, count: int) -> list[dict]:
        """Топ-N органических результатов как fallback."""
        results: list[dict] = []
        try:
            root = ET.fromstring(xml_text)
            for doc in root.findall(".//doc")[:count]:
                title_el = doc.find("title")
                snippet_el = doc.find(".//passages/passage") or doc.find("headline")
                results.append(
                    {
                        "title": title_el.text if title_el is not None else "",
                        "snippet": snippet_el.text if snippet_el is not None else "",
                    }
                )
        except ET.ParseError:
            pass
        return results
