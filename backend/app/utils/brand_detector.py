import re
from urllib.parse import urlparse

import tldextract


def extract_brand_from_url(url: str) -> str:
    """Извлекает название бренда из домена сайта."""
    extracted = tldextract.extract(url)
    domain = extracted.domain
    # Убираем цифры и спецсимволы, делаем Title Case
    brand = re.sub(r"[^a-zа-яё]", " ", domain.lower()).strip()
    return brand.title() if brand else domain.title()
