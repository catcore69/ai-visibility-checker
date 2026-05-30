import httpx

from app.llm_pollers.base import BasePoller, RateLimitError


class PerplexityPoller(BasePoller):
    name = "perplexity"
    display_name = "Perplexity"
    model = "llama-3.1-sonar-small-128k-online"

    async def _query_raw(self, prompt: str, region: str = "") -> str:
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.PERPLEXITY_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.7,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 429:
                raise RateLimitError("Perplexity rate limit")
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
