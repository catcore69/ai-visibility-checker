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

    async def _query_raw(self, prompt: str, region: str = "") -> str:
        # Гео-привязка: для белорусского клиента — белорусская выдача (lr=BY),
        # иначе российская. Раньше был хардкод _RU — белорусам приходила РФ-выдача
        # без локальных фирм.
        is_by = any(s in (region or "").lower() for s in ("беларус", " рб", "by"))
        lr = self.config.XMLRIVER_REGION_BY if is_by else self.config.XMLRIVER_REGION_RU
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

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 429:
                raise RateLimitError("XMLRiver rate limit")
            response.raise_for_status()

            neuro_text = self._extract_neuro_block(response.text)
            if neuro_text:
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
