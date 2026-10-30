from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from .models import DepositRequest, PaymentAccount, Transaction, Wallet, WithdrawalRequest
from .services import WalletError, confirm_deposit, mark_withdrawal_paid


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "balance", "held", "updated_at")
    list_filter = ("kind",)
    search_fields = ("user__phone", "user__full_name")
    readonly_fields = ("user", "kind", "balance", "held")

    def has_add_permission(self, request):
        return False


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "wallet", "kind", "amount", "held_delta", "balance_after", "reference", "project")
    list_filter = ("kind",)
    search_fields = ("reference", "wallet__user__phone")
    readonly_fields = [f.name for f in Transaction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DepositRequest)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "amount", "method", "external_ref", "status", "created_at")
    list_filter = ("status", "method")
    search_fields = ("reference", "external_ref", "user__phone")
    readonly_fields = ("reference", "user", "amount", "method", "gateway_payload", "confirmed_by", "confirmed_at")
    actions = ["confirm"]

    @admin.action(description=_("Confirmer les dépôts sélectionnés"))
    def confirm(self, request, queryset):
        for d in queryset.filter(status__in=["pending", "proof"]):
            try:
                confirm_deposit(d, by=request.user)
            except WalletError as e:
                messages.error(request, f"{d}: {e}")


@admin.register(WithdrawalRequest)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ("reference", "user", "amount", "fee", "method", "destination", "status", "created_at")
    list_filter = ("status", "method")
    search_fields = ("reference", "user__phone", "destination")
    readonly_fields = ("reference", "user", "amount", "fee", "method", "destination", "processed_by", "processed_at")
    actions = ["paid"]

    @admin.action(description=_("Marquer comme payés"))
    def paid(self, request, queryset):
        for w in queryset.filter(status="pending"):
            mark_withdrawal_paid(w, by=request.user)


@admin.register(PaymentAccount)
class PaymentAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "method", "number", "holder_name", "is_default", "is_active", "verified_at", "created_at")
    list_filter = ("method", "is_active")
    search_fields = ("user__phone", "user__full_name", "number", "holder_name")
    actions = ["mark_verified"]

    @admin.action(description=_("Marquer comme vérifiés"))
    def mark_verified(self, request, queryset):
        from django.utils import timezone

        queryset.filter(verified_at__isnull=True).update(verified_at=timezone.now())
