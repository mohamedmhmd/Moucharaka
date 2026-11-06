from django.contrib import admin

from .models import Contract, Signature


class SignatureInline(admin.TabularInline):
    model = Signature
    fk_name = "contract"
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in Signature._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    """Signed contracts are evidence: read-only. Open them on the site to read or print them."""
    list_display = ("reference", "kind", "status", "project", "created_by", "signed_at")
    list_filter = ("kind", "status")
    search_fields = ("reference", "project__title", "created_by__phone", "created_by__full_name", "object_ref")
    readonly_fields = [f.name for f in Contract._meta.fields if f.name != "viewers"] + ["viewers"]
    inlines = [SignatureInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def view_on_site(self, obj):
        return obj.get_absolute_url()
