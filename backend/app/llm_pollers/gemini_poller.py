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

    async def _query_raw(self, prompt: str) -> str:
        try:
            response = await self._model.generate_content_async(
                prompt,
                generation_config={"temperature": 0.7, "max_output_tokens": 500},
            )
            return response.text
        except ResourceExhausted as exc:
            raise RateLimitError(str(exc)) from exc
