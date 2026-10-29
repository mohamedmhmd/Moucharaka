from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils.translation import gettext as _


def approved_required(view):
    """Logged in AND identity approved by the compliance team."""

    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_approved:
            if user.status == user.Status.NEW:
                messages.info(request, _("Complétez la vérification de votre identité pour continuer."))
                return redirect("accounts:kyc")
            messages.warning(request, _("Votre compte doit être validé par notre équipe avant cette action."))
            return redirect("accounts:kyc_status")
        return view(request, *args, **kwargs)

    return wrapper


def staff_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect("core:home")
        return view(request, *args, **kwargs)

    return wrapper
