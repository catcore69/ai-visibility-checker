from openai import AsyncOpenAI, RateLimitError as OpenAIRateLimitError

from app.llm_pollers.base import BasePoller, RateLimitError


class OpenAIPoller(BasePoller):
    name = "chatgpt"
    display_name = "ChatGPT"
    model = "gpt-4o-mini"

    def __init__(self, cache, config):
        super().__init__(cache, config)
        self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)

    async def _query_raw(self, prompt: str, region: str = "") -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты помощник, который отвечает на вопросы пользователей. "
                            "Отвечай как в обычном чате с ChatGPT — кратко, с конкретными рекомендациями."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=500,
            )
            return response.choices[0].message.content or ""
        except OpenAIRateLimitError as exc:
            raise RateLimitError(str(exc)) from exc
