from django.contrib import admin

from .models import Distribution, Holding, Investment, Payout


@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "investor", "project", "shares", "amount", "status")
    list_filter = ("status",)
    search_fields = ("investor__phone", "project__title", "reference")


@admin.register(Holding)
class HoldingAdmin(admin.ModelAdmin):
    list_display = ("user", "project", "shares", "locked_shares", "cost_basis", "received_total")
    search_fields = ("user__phone", "project__title")


class PayoutInline(admin.TabularInline):
    model = Payout
    extra = 0
    readonly_fields = ("user", "shares", "amount")


@admin.register(Distribution)
class DistributionAdmin(admin.ModelAdmin):
    list_display = ("paid_at", "project", "kind", "gross_amount", "platform_fee", "net_amount", "on_time")
    list_filter = ("kind", "on_time")
    inlines = [PayoutInline]
