import mimetypes
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.utils import N_, audit, client_ip, notify

from .forms import (KYCForm, LoginForm, NewPasswordForm, OTPForm, PhoneOnlyForm, PhoneStartForm,
                    RegisterFinishForm, SettingsForm)
from .models import KYCProfile, PhoneOTP, User
from .otp import OTPError, issue_otp, verify_otp

VERIFIED_TTL = 15 * 60  # seconds a verified phone stays valid in the session


def _send_code(request, phone, purpose):
    try:
        code = issue_otp(phone, purpose, ip=client_ip(request))
    except OTPError as e:
        messages.error(request, str(e))
        return False
    if settings.DEBUG and settings.SMS_FALLBACK_BACKEND == "console":
        messages.info(request, _("Mode développement : votre code est %(code)s") % {"code": code})
    return True


def _mark_verified(request, phone, purpose):
    request.session[f"verified_{purpose}"] = {"phone": phone, "at": time.time()}


def _verified_phone(request, purpose):
    data = request.session.get(f"verified_{purpose}")
    if not data or time.time() - data["at"] > VERIFIED_TTL:
        return None
    return data["phone"]


# ------------------------------------------------------------------ registration

def register(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = PhoneStartForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        if _send_code(request, phone, PhoneOTP.Purpose.REGISTER):
            request.session["otp_phone"] = phone
            request.session["otp_purpose"] = PhoneOTP.Purpose.REGISTER
            return redirect("accounts:verify")
    return render(request, "accounts/register.html", {"form": form, "step": 1})


def verify(request):
    phone = request.session.get("otp_phone")
    purpose = request.session.get("otp_purpose")
    if not phone or not purpose:
        return redirect("accounts:register")
    form = OTPForm(request.POST or None)
    if request.method == "POST":
        if "resend" in request.POST:
            if _send_code(request, phone, purpose):
                messages.success(request, _("Un nouveau code a été envoyé."))
            return redirect("accounts:verify")
        if form.is_valid():
            try:
                verify_otp(phone, purpose, form.cleaned_data["code"])
            except OTPError as e:
                form.add_error("code", str(e))
            else:
                _mark_verified(request, phone, purpose)
                next_url = {
                    PhoneOTP.Purpose.REGISTER: "accounts:register_finish",
                    PhoneOTP.Purpose.RESET: "accounts:reset_finish",
                    PhoneOTP.Purpose.LOGIN: "accounts:otp_login_finish",
                }[purpose]
                return redirect(next_url)
    return render(request, "accounts/verify.html", {
        "form": form, "phone": phone, "purpose": purpose, "step": 2,
        "ttl_minutes": settings.OTP_TTL_SECONDS // 60})


def register_finish(request):
    phone = _verified_phone(request, PhoneOTP.Purpose.REGISTER)
    if not phone:
        messages.warning(request, _("Vérifiez d'abord votre numéro."))
        return redirect("accounts:register")
    form = RegisterFinishForm(request.POST or None, initial={"preferred_language": translation.get_language()})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if User.objects.filter(phone=phone).exists():
            messages.error(request, _("Ce numéro a déjà un compte. Connectez-vous."))
            return redirect("accounts:login")
        user = User.objects.create_user(
            phone, d["password1"], full_name=d["full_name"], email=d["email"],
            preferred_language=d["preferred_language"], phone_verified_at=timezone.now())
        request.session.pop("verified_register", None)
        login(request, user, backend="apps.accounts.backends.PhoneBackend")
        audit("user.registered", user, actor=user, request=request)
        messages.success(request, _("Compte créé. Dernière étape : vérifier votre identité."))
        return redirect("accounts:kyc")
    return render(request, "accounts/register_finish.html", {"form": form, "step": 3, "phone": phone})


# ------------------------------------------------------------------ KYC

@login_required
def kyc(request):
    user = request.user
    instance = KYCProfile.objects.filter(user=user).first()
    if instance and instance.status in (KYCProfile.Status.SUBMITTED, KYCProfile.Status.APPROVED):
        return redirect("accounts:kyc_status")
    initial = {"full_name_fr": user.full_name} if not instance else None
    form = KYCForm(request.POST or None, request.FILES or None, instance=instance, initial=initial)
    if request.method == "POST" and form.is_valid():
        profile = form.save(commit=False)
        profile.user = user
        profile.status = KYCProfile.Status.SUBMITTED
        profile.submitted_at = timezone.now()
        profile.terms_accepted_at = profile.terms_accepted_at or timezone.now()
        profile.save()
        user.status = User.Status.PENDING
        user.save(update_fields=["status"])
        audit("kyc.submitted", profile, actor=user, request=request)
        for staff in User.objects.filter(is_staff=True, is_active=True):
            notify(staff, N_("Nouveau dossier KYC à vérifier"), profile.full_name_fr, url="/staff/kyc/")
        messages.success(request, _("Dossier envoyé. Notre équipe le vérifie, vous recevrez un SMS."))
        return redirect("accounts:kyc_status")
    return render(request, "accounts/kyc.html", {"form": form, "kyc": instance})


@login_required
def kyc_status(request):
    profile = KYCProfile.objects.filter(user=request.user).first()
    return render(request, "accounts/kyc_status.html", {"kyc": profile})


@login_required
def kyc_document(request, user_id, field):
    """Serve an identity document to its owner or to staff only."""
    if field not in ("id_front", "id_back", "selfie", "proof_of_address"):
        raise Http404
    if not (request.user.is_staff or request.user.pk == user_id):
        raise Http404
    profile = get_object_or_404(KYCProfile, user_id=user_id)
    f = getattr(profile, field)
    if not f:
        raise Http404
    if request.user.is_staff and request.user.pk != user_id:
        audit("kyc.document_viewed", profile, actor=request.user, request=request, field=field)
    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    resp = FileResponse(f.open("rb"), content_type=ctype)
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ------------------------------------------------------------------ login / logout / reset

def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        from django.contrib.auth import authenticate

        user = authenticate(request, phone=form.cleaned_data["phone"], password=form.cleaned_data["password"])
        if user is None:
            form.add_error(None, _("Numéro ou mot de passe incorrect."))
        elif user.status == User.Status.SUSPENDED:
            form.add_error(None, _("Ce compte est suspendu. Contactez le support."))
        else:
            login(request, user)
            translation.activate(user.preferred_language)
            resp = redirect(request.GET.get("next") or "core:dashboard")
            resp.set_cookie(settings.LANGUAGE_COOKIE_NAME, user.preferred_language)
            return resp
    return render(request, "accounts/login.html", {"form": form})


def otp_login(request):
    """Passwordless login with an SMS code (useful on shared phones)."""
    form = PhoneOnlyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        if User.objects.filter(phone=phone, is_active=True).exists():
            if not _send_code(request, phone, PhoneOTP.Purpose.LOGIN):
                return render(request, "accounts/otp_login.html", {"form": form})
        request.session["otp_phone"] = phone
        request.session["otp_purpose"] = PhoneOTP.Purpose.LOGIN
        return redirect("accounts:verify")
    return render(request, "accounts/otp_login.html", {"form": form})


def otp_login_finish(request):
    phone = _verified_phone(request, PhoneOTP.Purpose.LOGIN)
    user = User.objects.filter(phone=phone, is_active=True).first() if phone else None
    if not user or user.status == User.Status.SUSPENDED:
        return redirect("accounts:login")
    request.session.pop("verified_login", None)
    login(request, user, backend="apps.accounts.backends.PhoneBackend")
    return redirect("core:dashboard")


def reset_start(request):
    form = PhoneOnlyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        # Same response whether or not the account exists (no enumeration).
        if User.objects.filter(phone=phone).exists():
            if not _send_code(request, phone, PhoneOTP.Purpose.RESET):
                return render(request, "accounts/reset_start.html", {"form": form})
        request.session["otp_phone"] = phone
        request.session["otp_purpose"] = PhoneOTP.Purpose.RESET
        return redirect("accounts:verify")
    return render(request, "accounts/reset_start.html", {"form": form})


def reset_finish(request):
    phone = _verified_phone(request, PhoneOTP.Purpose.RESET)
    user = User.objects.filter(phone=phone).first() if phone else None
    if not user:
        return redirect("accounts:reset")
    form = NewPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user.set_password(form.cleaned_data["password1"])
        user.save(update_fields=["password"])
        request.session.pop("verified_reset", None)
        audit("user.password_reset", user, actor=user, request=request)
        messages.success(request, _("Mot de passe modifié. Connectez-vous."))
        return redirect("accounts:login")
    return render(request, "accounts/reset_finish.html", {"form": form})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("core:home")


@login_required
def settings_view(request):
    form = SettingsForm(request.POST or None, instance=request.user)
    pwd_form = NewPasswordForm(request.POST or None, prefix="pwd") if "pwd-password1" in request.POST else NewPasswordForm(prefix="pwd")
    if request.method == "POST":
        if "pwd-password1" in request.POST:
            if pwd_form.is_valid():
                request.user.set_password(pwd_form.cleaned_data["password1"])
                request.user.save(update_fields=["password"])
                update_session_auth_hash(request, request.user)
                messages.success(request, _("Mot de passe modifié."))
                return redirect("accounts:settings")
        elif form.is_valid():
            form.save()
            messages.success(request, _("Préférences enregistrées."))
            resp = redirect("accounts:settings")
            resp.set_cookie(settings.LANGUAGE_COOKIE_NAME, request.user.preferred_language)
            return resp
    return render(request, "accounts/settings.html", {"form": form, "pwd_form": pwd_form})
