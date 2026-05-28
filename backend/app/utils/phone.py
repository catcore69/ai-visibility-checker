"""Нормализация и антиспам-проверка телефонов (Этап 5.2.2 ТЗ).

Без внешних зависимостей (phonenumbers) — для MVP достаточно простой
нормализации форматов РФ (+7) и Беларуси (+375) в E.164-подобный вид.
"""

import re

_DIGITS_RE = re.compile(r"\D+")


def normalize_phone(raw: str) -> tuple[str | None, bool]:
    """Нормализует телефон в формат +7XXXXXXXXXX / +375XXXXXXXXX.

    Возвращает (normalized, is_valid). Поддержка РФ и Беларуси.
    """
    if not raw:
        return None, False
    digits = _DIGITS_RE.sub("", raw)

    # РФ: 8XXXXXXXXXX или 7XXXXXXXXXX (11 цифр) → +7XXXXXXXXXX
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return "+7" + digits[1:], True
    # РФ без кода страны: 10 цифр → +7
    if len(digits) == 10:
        return "+7" + digits, True
    # Беларусь: 375XXXXXXXXX (12 цифр) → +375XXXXXXXXX
    if len(digits) == 12 and digits.startswith("375"):
        return "+375" + digits[3:], True

    return None, False


# Мусорные паттерны телефонов (ТЗ 5.2.2).
_SPAM_NUMBERS = {
    "+79999999999",
    "+78005553535",
    "+71234567890",
    "+70000000000",
}


def is_suspicious_phone(normalized: str | None) -> bool:
    """True, если телефон похож на мусор.

    Критерии: известные мусорные номера, либо >5 одинаковых цифр подряд.
    Спам всё равно сохраняем (вдруг человек ошибся), но эксперту в Telegram
    о таком лиде не пишем — он сам решит при просмотре.
    """
    if not normalized:
        return False
    if normalized in _SPAM_NUMBERS:
        return True
    # 6+ одинаковых цифр подряд
    if re.search(r"(\d)\1{5,}", normalized):
        return True
    # Монотонная последовательность 1234567 / 7654321
    digits = _DIGITS_RE.sub("", normalized)
    if "1234567" in digits or "7654321" in digits or "0123456" in digits:
        return True
    return False
