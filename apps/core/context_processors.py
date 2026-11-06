from django.conf import settings
from django.utils.translation import get_language_bidi


def platform(request):
    from apps.core.models import PlatformSettings

    ctx = {"PLATFORM_NAME": settings.PLATFORM_NAME, "IS_RTL": get_language_bidi(), "DEBUG": settings.DEBUG,
           "CONTACT_EMAIL": PlatformSettings.get().contact_email}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        ctx["unread_count"] = user.notifications.filter(is_read=False).count()
        if user.is_approved:
            from apps.wallet.models import Wallet

            ctx["nav_wallet"] = Wallet.for_user(user)
    return ctx
