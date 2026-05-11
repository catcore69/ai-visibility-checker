import re
from urllib.parse import urlparse

import tldextract


def normalize_url(url: str) -> str:
    """Нормализует URL: убирает схему, www, trailing slash."""
    url = url.strip().lower()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    netloc = parsed.netloc.replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def extract_root_domain(url: str) -> str:
    """Извлекает корневой домен (без www и поддоменов)."""
    extracted = tldextract.extract(url)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    return url


def canonical_keys(url: str, brand: str) -> tuple[str, str]:
    """
    Возвращает два ключа для rate-limit:
    - domain_key: только домен
    - domain_brand_key: домен + нормализованный бренд
    """
    domain = extract_root_domain(url)
    normalized_brand = re.sub(r"[\s\-_.]", "", brand.lower())
    return domain, f"{domain}:{normalized_brand}"


def mask_email(email: str) -> str:
    """j****@gmail.com"""
    parts = email.split("@")
    if len(parts) != 2:
        return email
    name, domain = parts
    if len(name) <= 1:
        return f"*@{domain}"
    return f"{name[0]}****@{domain}"


def extract_brand_from_url(url: str) -> str:
    """Извлекает название бренда из URL (домен без www, tld и дефисов)."""
    domain = extract_root_domain(url)
    # Take the main part before the TLD
    parts = domain.split('.')
    brand = parts[0] if parts else domain
    # Capitalize first letter
    return brand.capitalize() if brand else url
