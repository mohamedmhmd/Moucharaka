from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from .models import SMSMessage, SMSProvider
from .service import send_sms


@admin.register(SMSProvider)
class SMSProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "backend", "is_active", "priority", "prefixes", "sent_count", "failed_count")
    list_editable = ("is_active", "priority")
    actions = ["send_test"]

    @admin.action(description=_("Envoyer un SMS de test à mon numéro"))
    def send_test(self, request, queryset):
        ok = send_sms(request.user.phone, "Moucharaka: test SMS OK", purpose="test")
        if ok:
            messages.success(request, _("SMS de test envoyé."))
        else:
            messages.error(request, _("Aucun fournisseur n'a accepté le message. Consultez le journal SMS."))


@admin.register(SMSMessage)
class SMSMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "phone", "purpose", "backend", "provider", "status")
    list_filter = ("status", "purpose", "backend")
    search_fields = ("phone",)
    readonly_fields = [f.name for f in SMSMessage._meta.fields]

    def has_add_permission(self, request):
        return False
