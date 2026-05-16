import time
import uuid

import httpx

from app.llm_pollers.base import BasePoller, RateLimitError


class GigaChatPoller(BasePoller):
    name = "gigachat"
    display_name = "GigaChat (Сбер)"
    model = "GigaChat-Lite"

    def __init__(self, cache, config):
        super().__init__(cache, config)
        self._access_token: str | None = None
        self._token_expires_at: float = 0

    async def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        headers = {
            "Authorization": f"Basic {self.config.GIGACHAT_AUTH_KEY}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # verify=False — Сбер использует собственный CA
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            resp = await client.post(url, data={"scope": "GIGACHAT_API_PERS"}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + 1800
            return self._access_token

    async def _query_raw(self, prompt: str) -> str:
        token = await self._get_access_token()
        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "GigaChat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 500,
        }
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 429:
                raise RateLimitError("GigaChat rate limit")
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
