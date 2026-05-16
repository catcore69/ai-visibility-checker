"""
Одноразовый скрипт: регистрирует у Telegram webhook на наш бэкенд.

Запускать ОДИН раз после деплоя или при смене домена/токена.

    docker compose -f docker-compose.prod.yml exec backend \\
        python -m scripts.set_telegram_webhook https://catcore.ru

Или сухой пробег (просто покажет URL и секрет):

    python -m scripts.set_telegram_webhook --dry-run
"""
import asyncio
import sys
from typing import Optional

import httpx

from app.config import settings
from app.integrations.telegram_webhook import expected_webhook_secret


async def set_webhook(base_url: str, dry_run: bool = False) -> None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        print("[!] TELEGRAM_BOT_TOKEN не задан в .env — нечего регистрировать.")
        sys.exit(1)

    secret = expected_webhook_secret()
    webhook_url = f"{base_url.rstrip('/')}/api/v1/telegram/webhook/{secret}"

    print(f"Webhook URL: {webhook_url}")
    print(f"Bot token tail: ...{token[-6:]}")

    if dry_run:
        print("(dry-run, ничего не отправляем)")
        return

    base = (settings.TELEGRAM_API_BASE or "https://api.telegram.org").rstrip("/")
    api = f"{base}/bot{token}"
    proxy = settings.TELEGRAM_PROXY_URL or None
    if base != "https://api.telegram.org":
        print(f"Using relay: {base}")
    if proxy:
        print(f"Using proxy: {proxy.split('@')[-1]}")
    async with httpx.AsyncClient(timeout=15.0, proxy=proxy) as client:
        r = await client.post(f"{api}/setWebhook", json={
            "url": webhook_url,
            "allowed_updates": ["callback_query", "message"],
            "drop_pending_updates": True,
        })
        print(f"setWebhook → {r.status_code}: {r.text}")

        info = await client.get(f"{api}/getWebhookInfo")
        print(f"getWebhookInfo: {info.text}")


def main(argv: Optional[list[str]] = None) -> None:
    argv = argv or sys.argv[1:]
    dry = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]

    base_url = args[0] if args else settings.STUDIO_FULL_URL
    if not base_url:
        print("Usage: python -m scripts.set_telegram_webhook https://catcore.ru")
        sys.exit(1)

    asyncio.run(set_webhook(base_url, dry_run=dry))


if __name__ == "__main__":
    main()
