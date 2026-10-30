from django.contrib import admin, messages
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from .models import SMSMessage, SMSProvider
from .service import send_otp


@admin.register(SMSProvider)
class SMSProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "channel", "backend", "is_active", "priority", "prefixes", "sent_count", "failed_count")
    list_editable = ("is_active", "priority")
    list_filter = ("channel", "backend", "is_active")
    actions = ["send_test"]

    @admin.action(description=_("Envoyer un code de test à mon numéro"))
    def send_test(self, request, queryset):
        channel = send_otp(request.user.phone, "123456", "Moucharaka : code de test 123456", lang=get_language() or "fr")
        if channel:
            messages.success(request, _("Code de test envoyé par %(c)s.") % {"c": channel})
        else:
            messages.error(request, _("Aucun fournisseur n'a accepté le message. Consultez le journal des messages."))


@admin.register(SMSMessage)
class SMSMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "phone", "channel", "purpose", "backend", "provider", "status")
    list_filter = ("channel", "status", "purpose", "backend")
    search_fields = ("phone",)
    readonly_fields = [f.name for f in SMSMessage._meta.fields]

    def has_add_permission(self, request):
        return False
