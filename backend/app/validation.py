"""Server-side validation helpers. Caller speech, model arguments and dashboard text are
all treated as untrusted input."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers

ZIP_RE = re.compile(r"^\d{5}$")


def normalize_us_phone(raw: str | None) -> str | None:
    """Return E.164 for a valid US/NANP number, else None."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", str(raw))[:20]
    try:
        parsed = phonenumbers.parse(digits, "US")
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed) or parsed.country_code != 1:
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_zip(raw: str | None) -> str | None:
    if raw is None:
        return None
    z = re.sub(r"\D", "", str(raw))[:5]
    return z if ZIP_RE.match(z) else None


def valid_timezone(tz: str) -> bool:
    try:
        ZoneInfo(tz)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def clean_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(value)).strip()
    return value[:limit] or None
