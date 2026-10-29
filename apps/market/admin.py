from django.contrib import admin

from .models import Listing, Trade


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("project", "seller", "shares", "remaining", "price_per_share", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("project__title", "seller__phone")


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    list_display = ("created_at", "project", "buyer", "seller", "shares", "price_per_share", "buyer_fee", "seller_fee")
    readonly_fields = [f.name for f in Trade._meta.fields]

    def has_add_permission(self, request):
        return False
