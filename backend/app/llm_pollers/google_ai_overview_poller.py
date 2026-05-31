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

    def __init__(self, cache, config):
        super().__init__(cache, config)
        # Citations per prompt — собираются в _query_raw, забираются pipeline'ом
        # после opроса для построения Блока А «прямые конкуренты». Это URL,
        # на которые AI Overview ссылается — детерминированные реальные сайты,
        # не галлюцинации LLM-моделей. См. ТЗ catcore-blok-a-iz-realnoy-vydachi.
        self._citations: dict[str, list[str]] = {}

    def consume_citations(self) -> dict[str, list[str]]:
        """Pipeline вызывает после polling, чтобы забрать citations
        и сбросить storage. Формат: {prompt: [url, url, ...]}."""
        out = dict(self._citations)
        self._citations.clear()
        return out

    async def _query_raw(self, prompt: str, region: str = "") -> str:
        # КРИТИЧНЫЙ ФИКС 31.05.26 (после серии curl-тестов с поддержкой):
        # Для БР-локали (country=2112+loc=2112) XMLRiver возвращает error 15
        # «нет результатов» на ЛЮБОМ русскоязычном запросе — даже без ai=1,
        # даже на чистую органику. Это ограничение их сервиса для БР-зоны.
        # При этом для РФ-локали (country=2643+loc=2643+ai=1+headers) запрос
        # возвращает 8 KB органики; для US (country=2840+loc=2840) — <ai>
        # с реальным AI Overview.
        #
        # Решение: ВСЕМ русскоязычным клиентам шлём country=loc=RU (2643).
        # Google AI Overview поймёт из текста запроса («минск», «в Беларуси»),
        # о каком регионе речь, и упомянёт локальных игроков. Это та же
        # стратегия, что у Yandex-Нейро (lr=225 для всех). У юзера в браузере
        # Алиса работает точно так же — её Яндекс/Google по умолчанию идут
        # под РФ-локалью даже из БР.
        #
        # loc=country (страна, не город): подтверждено curl-тестом 31.05 —
        # с loc=2643 (=country) и headers запрос РАБОТАЕТ; с loc=1011969
        # (Москва-город) тот же запрос даёт error 15. Поддержка ввела
        # в заблуждение про «loc=город», на самом деле loc=country валиден.
        country = self.config.XMLRIVER_GOOGLE_COUNTRY_RU  # 2643 для всех
        loc = country  # loc=country проверено рабочим
        url = "https://xmlriver.com/search/xml"
        # ai=1 — отдельный платный параметр для парсинга «Обзора от ИИ» Google.
        # Симметричен neuro=1 у Yandex-эндпоинта. Источник: api-about/.
        params = {
            "user": self.config.XMLRIVER_USER,
            "key": self.config.XMLRIVER_KEY,
            "query": prompt,
            "country": country,
            "loc": loc,
            "ai": "1",
        }
        # КРИТИЧНЫЙ ФИКС 31.05.26: XMLRiver на /search/xml без User-Agent и
        # Accept-Language отвечает error 15 «отсутствуют результаты» на ВСЕХ
        # русских запросах (антибот-фильтр). Подтверждено серией curl-тестов:
        # тот же URL без заголовков → error 15, с заголовками браузера → 7KB
        # нормальной выдачи. Поддержка проверяла «у нас в браузере работает»
        # именно потому, что браузер шлёт эти заголовки. Httpx-дефолт их не шлёт.
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
                raise RateLimitError("XMLRiver Google rate limit")
            response.raise_for_status()
            # Citations (URL-источники AI Overview) сохраняем в storage —
            # их забирает pipeline через consume_citations() для построения
            # Блока А «прямые конкуренты».
            try:
                cits = self.extract_citations(response.text)
                if cits:
                    self._citations[prompt] = cits
            except Exception:
                pass
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
