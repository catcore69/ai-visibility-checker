from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError

from app.llm_pollers.base import BasePoller, RateLimitError


class DeepSeekPoller(BasePoller):
    name = "deepseek"
    display_name = "DeepSeek"
    model = "deepseek-chat"

    def __init__(self, cache, config):
        super().__init__(cache, config)
        self.client = AsyncOpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )

    async def _query_raw(self, prompt: str) -> str:
        try:
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=500,
            )
            return response.choices[0].message.content or ""
        except OpenAIRateLimitError as exc:
            raise RateLimitError(str(exc)) from exc
