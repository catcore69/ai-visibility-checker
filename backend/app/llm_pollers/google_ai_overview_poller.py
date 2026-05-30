"""Google AI Overview (Обзор от ИИ) — AI-блок в поисковой выдаче Google.

Это НЕ Gemini (модель через API), а ровно тот блок, который Google показывает
в верху поисковой выдачи на части запросов. Симметрично к нашему
«Яндекс-поиск с AI-блоком».

Источник: XMLRiver /search_google/xml + платные параметры AI Overview
(включаются галочкой в кабинете https://xmlriver.com/queries/). Без них
ответ содержит только `<present>1</present>` без текста — этого недостаточно
для анализа упоминаний.

Структура ответа XMLRiver:
    <ai>
      <answer>base64(HTML сгенерированного ответа)</answer>
      <item>
        <title>...</title>
        <snippet>...</snippet>
        <url>...</url>      ← citations
      </item>
      ...
    </ai>

Покрытие: Google показывает AI Overview не на 100% запросов (особенно на
русскоязычных региональных). Если по запросу блок не показан — это валидный
результат «не показан», не ошибка. В отчёте честно помечаем.
"""

import base64
import re
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from app.llm_pollers.base import BasePoller, RateLimitError


class GoogleAIOverviewPoller(BasePoller):
    name = "google_ai_overview"
    display_name = "Google AI Overview"
    model = "google-ai-overview"

    async def _query_raw(self, prompt: str, region: str = "") -> str:
        # Google country: 2643=Россия, 2112=Беларусь (это Google geo IDs,
        # НЕ Yandex lr). Источник: документация XMLRiver /apidoc/api-about/.
        # Раньше шли с country=149 (Yandex lr для РБ) → ошибка «Неверный loc».
        is_by = any(s in (region or "").lower() for s in ("беларус", " рб", "by"))
        country = (
            self.config.XMLRIVER_GOOGLE_COUNTRY_BY
            if is_by
            else self.config.XMLRIVER_GOOGLE_COUNTRY_RU
        )
        # Правильный эндпоинт по проверенному рабочему запросу пользователя —
        # /search/xml (это и есть Google + AI Overview); /search_google/xml
        # возвращал пустоту с тем же ключом. country оставляем для региональности.
        url = "https://xmlriver.com/search/xml"
        params = {
            "user": self.config.XMLRIVER_USER,
            "key": self.config.XMLRIVER_KEY,
            "query": prompt,
            "groupby": "10",
            "country": country,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, params=params)
            if response.status_code == 429:
                raise RateLimitError("XMLRiver Google rate limit")
            response.raise_for_status()
            return self._extract_ai_overview(response.text)

    def _extract_ai_overview(self, xml_text: str) -> str:
        """Текст AI Overview: base64 → HTML → plain text. Если блока нет —
        честная заглушка (Google показал не на этот запрос, не ошибка)."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return "[Google AI Overview: не удалось распарсить ответ XMLRiver]"

        ai = root.find(".//ai")
        if ai is None:
            return "[Google AI Overview не показан для этого запроса]"

        answer_el = ai.find("answer")
        if answer_el is None or not (answer_el.text or "").strip():
            # Без платных параметров может быть только <present>1</present>.
            present = ai.find("present")
            if present is not None and (present.text or "").strip() == "1":
                return (
                    "[AI Overview показан Google, но текст не извлечён — "
                    "проверь, что в кабинете XMLRiver включены платные "
                    "параметры AI Overview]"
                )
            return "[Google AI Overview не показан для этого запроса]"

        try:
            html_bytes = base64.b64decode(answer_el.text.strip())
            html_text = html_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return "[Google AI Overview: ошибка декодирования base64]"

        # Стрипим HTML-теги и сжимаем пробелы.
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = (
            text.replace("&nbsp;", " ")
            .replace("&mdash;", "—")
            .replace("&amp;", "&")
            .replace("&laquo;", "«")
            .replace("&raquo;", "»")
        )
        text = re.sub(r"\s+", " ", text).strip()
        return text or "[Google AI Overview: пустой ответ]"

    def extract_citations(self, xml_text: str) -> list[str]:
        """Citations (URL-источники), которые AI Overview подобрал. Используется
        отдельно от _query_raw для блока «источники» в отчёте."""
        urls: list[str] = []
        try:
            root = ET.fromstring(xml_text)
            ai = root.find(".//ai")
            if ai is None:
                return []
            for item in ai.findall("item"):
                url_el = item.find("url")
                if url_el is not None and url_el.text:
                    urls.append(url_el.text.strip())
        except ET.ParseError:
            pass
        return urls
