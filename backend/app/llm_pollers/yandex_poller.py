import httpx

from app.llm_pollers.base import BasePoller, RateLimitError


class YandexGPTPoller(BasePoller):
    name = "yandexgpt"
    display_name = "YandexGPT"
    model = "yandexgpt-lite"

    async def _query_raw(self, prompt: str, region: str = "") -> str:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {
            "Authorization": f"Api-Key {self.config.YANDEX_API_KEY}",
            "x-folder-id": self.config.YANDEX_FOLDER_ID,
            "Content-Type": "application/json",
        }
        payload = {
            "modelUri": f"gpt://{self.config.YANDEX_FOLDER_ID}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.7,
                "maxTokens": "500",
            },
            "messages": [{"role": "user", "text": prompt}],
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 429:
                raise RateLimitError("YandexGPT rate limit")
            response.raise_for_status()
            data = response.json()
            return data["result"]["alternatives"][0]["message"]["text"]
