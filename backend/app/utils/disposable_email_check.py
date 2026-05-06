"""Проверка на одноразовые email-адреса."""

DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "tempmail.com", "throwam.com",
    "sharklasers.com", "guerrillamailblock.com", "grr.la", "guerrillamail.info",
    "guerrillamail.biz", "guerrillamail.de", "guerrillamail.net", "guerrillamail.org",
    "spam4.me", "trashmail.com", "trashmail.me", "trashmail.net", "trashmail.at",
    "dispostable.com", "fakeinbox.com", "yopmail.com", "getnada.com",
    "maildrop.cc", "spamgourmet.com", "spamgourmet.net", "spamgourmet.org",
    "mailnull.com", "spamfree24.org", "mailexpire.com", "spamevader.com",
    "trashmail.io", "zetmail.com", "wegwerfmail.de", "wegwerfmail.net",
    "wegwerfmail.org", "spamhere.eu", "spamthis.co.uk", "jetable.fr.nf",
    "nomail.xl.cx", "mail.mezimages.net", "10minutemail.com", "10minutemail.net",
    "20minutemail.com", "discard.email", "throwam.com", "mohmal.com",
    "tempinbox.com", "nwytg.net", "spamgob.com", "txthub.com",
    # Русскоязычные одноразовые
    "mailnesia.com", "dispostable.com",
}


def is_disposable_email(email: str) -> bool:
    """Возвращает True если email с одноразового домена."""
    if "@" not in email:
        return False
    domain = email.split("@")[-1].lower()
    return domain in DISPOSABLE_DOMAINS
