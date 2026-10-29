from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Review, TrustEvent, TrustScore
from .services import compute_score


@admin.register(TrustScore)
class TrustScoreAdmin(admin.ModelAdmin):
    list_display = ("user", "score", "grade", "has_track_record", "computed_at")
    list_filter = ("grade",)
    search_fields = ("user__phone", "user__full_name")
    readonly_fields = ("components",)
    actions = ["recompute"]

    @admin.action(description=_("Recalculer"))
    def recompute(self, request, queryset):
        for s in queryset:
            compute_score(s.user)


@admin.register(TrustEvent)
class TrustEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "kind", "points", "project", "note")
    list_filter = ("kind",)
    search_fields = ("user__phone", "user__full_name", "note")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        compute_score(obj.user)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("project", "reviewer", "owner", "communication", "transparency", "commitments", "is_hidden")
    list_editable = ("is_hidden",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        compute_score(obj.owner)
