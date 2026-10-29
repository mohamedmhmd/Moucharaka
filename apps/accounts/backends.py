from django.contrib.auth.backends import ModelBackend

from .models import normalize_phone


class PhoneBackend(ModelBackend):
    """Authenticate with a Mauritanian phone number in any common format
    (22 12 34 56, +222 22123456, 0022222123456)."""

    def authenticate(self, request, username=None, password=None, phone=None, **kwargs):
        raw = phone or username or kwargs.get("phone")
        if raw is None:
            return None
        return super().authenticate(request, username=normalize_phone(raw), password=password)
