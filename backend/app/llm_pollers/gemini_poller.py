import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

from app.llm_pollers.base import BasePoller, RateLimitError


class GeminiPoller(BasePoller):
    name = "gemini"
    display_name = "Gemini"
    model = "gemini-2.0-flash"

    def __init__(self, cache, config):
        super().__init__(cache, config)
        genai.configure(api_key=config.GEMINI_API_KEY)
        self._model = genai.GenerativeModel(self.model)

    async def _query_raw(self, prompt: str, region: str = "") -> str:
        try:
            response = await self._model.generate_content_async(
                prompt,
                generation_config={"temperature": 0.7, "max_output_tokens": 500},
            )
        except ResourceExhausted as exc:
            raise RateLimitError(str(exc)) from exc

        # Gemini может вернуть пустой response.text БЕЗ exception, если
        # safety/policy его заблокировали или max_tokens hit. До этого мы
        # молча возвращали "" — и в отчёте было gemini 0/N без объяснений.
        # Теперь честно объясняем причину прямо в ответе (анализ упоминаний
        # его всё равно проигнорирует — слово не появится в нём), а в логе
        # видно finish_reason.
        from app.utils.logger import get_logger
        log = get_logger(__name__)

        try:
            text = response.text
            if text:
                return text
        except Exception:
            # SDK кидает ValueError, если response пуст (нет .text). Считаем — пусто.
            text = None

        # Разбираем, что именно случилось
        finish_reason = None
        safety_ratings = []
        try:
            if response.candidates:
                cand = response.candidates[0]
                finish_reason = getattr(cand, "finish_reason", None)
                if finish_reason is not None:
                    finish_reason = str(finish_reason)
                safety_ratings = [
                    str(getattr(r, "category", "?")) + ":" + str(getattr(r, "probability", "?"))
                    for r in (getattr(cand, "safety_ratings", []) or [])
                ]
        except Exception:
            pass

        prompt_block = None
        try:
            pf = getattr(response, "prompt_feedback", None)
            if pf is not None:
                prompt_block = str(getattr(pf, "block_reason", None) or "")
        except Exception:
            pass

        log.warning(
            "gemini_empty_response",
            finish_reason=finish_reason,
            prompt_block=prompt_block,
            safety=safety_ratings[:3],
            prompt_head=prompt[:80],
        )
        return f"[Gemini не вернул ответа: finish_reason={finish_reason or 'unknown'}; block={prompt_block or 'none'}]"
