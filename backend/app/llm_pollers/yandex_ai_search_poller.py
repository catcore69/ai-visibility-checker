import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from app.llm_pollers.base import BasePoller, RateLimitError


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
        params = {
            "user": self.config.XMLRIVER_USER,
            "key": self.config.XMLRIVER_KEY,
            "query": prompt,
            "lr": lr,
            # groupby убран: требует loc, без него XMLRiver кидает error 104.
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
        """Извлекает текст блока Нейро из ответа XMLRiver."""
        try:
            root = ET.fromstring(xml_text)
            # XMLRiver возвращает <response><neuro>...</neuro></response>
            # или вложенный элемент — уточняется по документации xmlriver.com/apidoc/
            for tag in ["neuro", "neural-answer", "ai-answer"]:
                neuro = root.find(f".//{tag}")
                if neuro is not None and neuro.text:
                    return neuro.text.strip()
            return None
        except ET.ParseError:
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
