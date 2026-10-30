"""International phone numbers.

Numbers are stored in E.164 format (+22222123456, +33612345678). Users can type
a Mauritanian number without the country code (22 12 34 56); any other country
needs the + and its code. Which countries may register is set by
PHONE_ALLOWED_COUNTRIES (protects against SMS-pumping fraud).
"""
import phonenumbers
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def parse(raw):
    text = str(raw or "").strip()
    if text.startswith("00"):
        text = "+" + text[2:]
    try:
        return phonenumbers.parse(text, settings.PHONE_DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        return None


def normalize_phone(raw) -> str:
    """Return E.164 (+22222123456), or the raw digits if the number can't be parsed."""
    num = parse(raw)
    if num is None:
        return "".join(c for c in str(raw or "") if c.isdigit() or c == "+")
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)


def region_of(e164) -> str:
    num = parse(e164)
    return phonenumbers.region_code_for_number(num) if num else ""


def national_number(e164) -> str:
    num = parse(e164)
    return phonenumbers.national_significant_number(num) if num else str(e164).lstrip("+")


def display_phone(e164) -> str:
    num = parse(e164)
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL) if num else str(e164 or "")


def validate_phone(value):
    num = parse(value)
    if num is None or not phonenumbers.is_valid_number(num):
        raise ValidationError(_("Numéro de téléphone invalide. Hors de Mauritanie, commencez par + et l'indicatif "
                                "du pays (ex. +33 6 12 34 56 78)."), code="invalid_phone")
    allowed = settings.PHONE_ALLOWED_COUNTRIES
    if "*" not in allowed and phonenumbers.region_code_for_number(num) not in allowed:
        raise ValidationError(_("L'inscription n'est pas encore ouverte aux numéros de ce pays."),
                              code="country_not_allowed")
