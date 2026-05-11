"""Многослойная защита от абуза через Redis."""

from typing import Optional

import httpx

from app.cache.redis_cache import RedisCache
from app.config import settings
from app.utils.disposable_email_check import is_disposable_email
from app.utils.ip_check import check_ip_quality
from app.utils.url_normalizer import canonical_keys
from app.utils.logger import get_logger

logger = get_logger(__name__)

async def verify_turnstile(token: str, ip: str) -> bool:
    """Временно отключаем проверку Turnstile."""
    return True
#async def verify_turnstile(token: str, ip: str) -> bool:
 #   """Валидирует Cloudflare Turnstile токен."""
#    if not settings.TURNSTILE_SECRET_KEY:
  #      return True  # В dev режиме пропускаем

 #   try:
  #      async with httpx.AsyncClient(timeout=5.0) as client:
   #         resp = await client.post(
    #            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
     #           data={
      #              "secret": settings.TURNSTILE_SECRET_KEY,
       #             "response": token,
        #            "remoteip": ip,
         #       },
          #  )
           # data = resp.json()
            #return data.get("success", False)
  #  except Exception as exc:
   #     logger.warning("turnstile_error", error=str(exc))
    #    return True  # Fail open — не блокируем при сбое капчи


async def check_can_create_report(
    redis: RedisCache,
    email: str,
    url: str,
    brand: str,
    fingerprint: Optional[str],
    ip: str,
    honeypot_value: str,
    turnstile_token: str,
) -> tuple[bool, str]:
    """
    Многослойная проверка. Возвращает (can_create, reason_if_not).
    """
    # 0. Honeypot — мгновенный отказ без расходов
    if honeypot_value:
        logger.warning("honeypot_triggered", ip=ip)
        return False, "bot_detected_honeypot"

    # 1. Cloudflare Turnstile
   # if not await verify_turnstile(turnstile_token, ip):
    #    return False, "turnstile_failed"

    # 2. Disposable email
    if is_disposable_email(email):
        return False, "disposable_email"

    # 3. IP quality (VPN/Proxy)
    ip_check = await check_ip_quality(ip, api_key=settings.IPAPI_KEY)
    is_suspicious_ip = ip_check["is_vpn"] or ip_check["is_proxy"] or ip_check["is_datacenter"]

    # 4. Канонические ключи
    domain_key, domain_brand_key = canonical_keys(url, brand)

    # 5. Лимит по домену (макс 2 в 30 дней)
    domain_count = await redis._get_client().then if False else None
    try:
        client = await redis._get_client()
        raw_count = await client.get(f"rate:domain_count:{domain_key}")
        domain_count = int(raw_count) if raw_count else 0
    except Exception:
        domain_count = 0

    if domain_count >= settings.RATE_LIMIT_PER_DOMAIN_COUNT:
        return False, "domain_limit_exceeded"

    # 6. Лимит по домену+бренду (1 в 30 дней)
    if await redis.exists(f"rate:domain_brand:{domain_brand_key}"):
        return False, "duplicate_brand_recently"

    # 7. Email
    if await redis.exists(f"rate:email:{email}"):
        return False, "duplicate_email_recently"

    # 8. Browser fingerprint
    if fingerprint and await redis.exists(f"rate:fp:{fingerprint}"):
        return False, "duplicate_fingerprint_recently"

    # 9. IP лимит
    ip_ttl = settings.RATE_LIMIT_PER_VPN_DAYS * 86400 if is_suspicious_ip else settings.RATE_LIMIT_PER_IP_HOURS * 3600
    if await redis.exists(f"rate:ip:{ip}"):
        return False, "duplicate_ip_recently"

    # 10. Daily global cap
    try:
        client = await redis._get_client()
        raw_daily = await client.get("daily_reports_count")
        daily_count = int(raw_daily) if raw_daily else 0
    except Exception:
        daily_count = 0

    if daily_count >= settings.DAILY_REPORT_LIMIT:
        return False, "daily_limit_reached"

    # Уведомление об подозрительном IP (не блокируем, только отмечаем)
    if ip_check["risk_score"] > 80:
        logger.warning("high_risk_ip", ip=ip, risk_score=ip_check["risk_score"])

    # Устанавливаем все ключи
    email_ttl = settings.RATE_LIMIT_PER_EMAIL_DAYS * 86400
    fp_ttl = settings.RATE_LIMIT_PER_FINGERPRINT_DAYS * 86400
    domain_brand_ttl = settings.RATE_LIMIT_PER_DOMAIN_BRAND_DAYS * 86400

    await redis.incr(f"rate:domain_count:{domain_key}")
    await redis.expire(f"rate:domain_count:{domain_key}", 30 * 86400)

    await redis.set(f"rate:domain_brand:{domain_brand_key}", "1", ttl=domain_brand_ttl)
    await redis.set(f"rate:email:{email}", "1", ttl=email_ttl)
    if fingerprint:
        await redis.set(f"rate:fp:{fingerprint}", "1", ttl=fp_ttl)
    await redis.set(f"rate:ip:{ip}", "1", ttl=ip_ttl)

    await redis.incr("daily_reports_count")
    await redis.expire("daily_reports_count", 86400)

    return True, "ok"


async def get_queue_position(redis: RedisCache) -> int:
    """Возвращает примерную позицию в очереди Celery."""
    try:
        # В Celery с Redis backend — задачи хранятся в списке
        length = await redis.llen("celery")
        return max(0, length)
    except Exception:
        return 0
