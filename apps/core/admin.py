from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import AuditLog, Moughataa, Notification, PlatformSettings, Wilaya


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (_("Marché secondaire"), {"fields": ("trade_fee_buyer_pct", "trade_fee_seller_pct", "max_listing_premium_pct")}),
        (_("Portefeuille"), {"fields": ("min_deposit", "min_withdrawal", "withdrawal_fee_flat", "withdrawal_fee_pct")}),
        (_("Protection des investisseurs"), {"fields": ("max_ticket_pct", "max_campaign_days")}),
        (_("Discipline des porteurs"), {"fields": ("report_grace_days", "installment_grace_days")}),
        (_("Revenus annexes"), {"fields": ("featured_fee",)}),
        (_("Contact"), {"fields": ("contact_email",)}),
        (_("Instructions de paiement"), {"fields": ("merchant_bankily", "merchant_masrvi", "merchant_sedad",
                                                   "bank_details", "support_phone")}),
    )

    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class MoughataaInline(admin.TabularInline):
    model = Moughataa
    extra = 0


@admin.register(Wilaya)
class WilayaAdmin(admin.ModelAdmin):
    list_display = ("name_fr", "name_ar", "code", "order")
    inlines = [MoughataaInline]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "title", "is_read")
    search_fields = ("user__phone", "title")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "target_repr", "ip")
    list_filter = ("action",)
    search_fields = ("target_repr", "actor__phone", "action")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
