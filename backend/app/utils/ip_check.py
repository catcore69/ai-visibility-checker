from typing import Optional

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)


async def check_ip_quality(ip: str, api_key: str = "") -> dict:
    """
    Проверяет IP через ipapi.is (1000 запросов в день бесплатно).
    Возвращает признаки VPN/Proxy/Datacenter и risk_score.
    """
    try:
        params = {"q": ip}
        if api_key:
            params["key"] = api_key

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://api.ipapi.is/", params=params)
            if resp.status_code != 200:
                return _default_result()
            data = resp.json()

        is_vpn = data.get("is_vpn", False)
        is_proxy = data.get("is_proxy", False)
        is_datacenter = data.get("is_datacenter", False)
        country = data.get("location", {}).get("country_code", "")

        risk_score = _calculate_risk_score(is_vpn, is_proxy, is_datacenter)

        return {
            "is_vpn": is_vpn,
            "is_proxy": is_proxy,
            "is_datacenter": is_datacenter,
            "country": country,
            "risk_score": risk_score,
        }
    except Exception as exc:
        logger.warning("ip_check_error", ip=ip, error=str(exc))
        return _default_result()


def _calculate_risk_score(is_vpn: bool, is_proxy: bool, is_datacenter: bool) -> int:
    score = 0
    if is_vpn:
        score += 40
    if is_proxy:
        score += 50
    if is_datacenter:
        score += 35
    return min(100, score)


def _default_result() -> dict:
    return {
        "is_vpn": False,
        "is_proxy": False,
        "is_datacenter": False,
        "country": "",
        "risk_score": 0,
    }
