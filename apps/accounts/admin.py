from django.contrib import admin, messages
from django import forms
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from .models import KYCProfile, PhoneOTP, User
from .phones import normalize_phone, validate_phone


class _PhoneCleanMixin:
    """Admin forms: accept any common format and store E.164, rejecting duplicates."""

    def clean_phone(self):
        raw = self.cleaned_data.get("phone")
        validate_phone(raw)
        phone = normalize_phone(raw)
        others = User.objects.filter(phone=phone)
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError(_("Un compte existe déjà avec ce numéro."))
        return phone


class AdminUserCreationForm(_PhoneCleanMixin, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("phone", "full_name")


class AdminUserChangeForm(_PhoneCleanMixin, UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"
from .services import approve_kyc, reject_kyc


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    ordering = ("-date_joined",)
    list_display = ("phone", "full_name", "status", "is_staff", "date_joined")
    list_filter = ("status", "is_staff", "is_active", "preferred_language")
    search_fields = ("phone", "full_name", "email", "kyc__nni")
    readonly_fields = ("public_id", "date_joined", "last_login", "phone_verified_at", "approved_at")
    fieldsets = (
        (None, {"fields": ("phone", "password", "public_id")}),
        (_("Profil"), {"fields": ("full_name", "email", "preferred_language", "status")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Dates"), {"fields": ("date_joined", "last_login", "phone_verified_at", "approved_at")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("phone", "full_name", "password1", "password2")}),)


@admin.register(KYCProfile)
class KYCProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "nni", "user", "wilaya", "status", "risk_level", "submitted_at", "review_link")
    list_filter = ("status", "risk_level", "is_pep", "wilaya", "id_type")
    search_fields = ("full_name", "nni", "id_number", "user__phone")
    readonly_fields = ("submitted_at", "reviewed_at", "reviewed_by", "terms_accepted_at", "documents")
    actions = ["approve", "request_corrections"]
    exclude = ("id_front", "id_back")

    @admin.display(description=_("Documents"))
    def documents(self, obj):
        rows = [(reverse("accounts:kyc_document", args=[obj.user_id, f]), KYCProfile._meta.get_field(f).verbose_name)
                for f in ("id_front", "id_back") if getattr(obj, f)]
        if not rows:
            return "—"
        return format_html_join(mark_safe("<br>"), '<a href="{}" target="_blank" rel="noopener">{}</a>', rows)

    @admin.display(description=_("Revue"))
    def review_link(self, obj):
        return format_html('<a href="{}">{}</a>', reverse("staff:kyc_review", args=[obj.pk]), _("Ouvrir"))

    @admin.action(description=_("Approuver les dossiers sélectionnés (risque faible)"))
    def approve(self, request, queryset):
        n = 0
        for p in queryset.filter(status=KYCProfile.Status.SUBMITTED):
            approve_kyc(p, request.user, request=request)
            n += 1
        messages.success(request, _("%(n)s dossier(s) approuvé(s).") % {"n": n})

    @admin.action(description=_("Demander des corrections (motif générique)"))
    def request_corrections(self, request, queryset):
        for p in queryset.filter(status=KYCProfile.Status.SUBMITTED):
            reject_kyc(p, request.user, str(_("Documents illisibles ou incomplets. Merci de les renvoyer.")), request=request)


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ("phone", "purpose", "created_at", "expires_at", "attempts", "consumed_at")
    list_filter = ("purpose",)
    search_fields = ("phone",)
    exclude = ("code_hash",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
