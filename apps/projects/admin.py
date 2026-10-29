from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from apps.investments.services import InvestmentError, release_funds

from .models import (BoutiqueMonth, BoutiqueProduct, BoutiqueProfile, CompanyPlan, DealPlan, FeePolicy,
                     FinancialReport, Installment, Milestone, Project, ProjectAnswer, ProjectDocument, ProjectImage,
                     ProjectionYear, ProjectQuestion, ProjectUpdate, Question, QuestionSection, Sector, TeamMember,
                     UseOfFunds)


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ("name_fr", "name_ar", "slug", "order")
    list_editable = ("order",)
    prepopulated_fields = {"slug": ("name_fr",)}


@admin.register(FeePolicy)
class FeePolicyAdmin(admin.ModelAdmin):
    list_display = ("kind", "financing_model", "review_fee", "success_fee_pct", "management_fee_pct",
                    "min_target", "max_target", "is_enabled")
    list_editable = ("review_fee", "success_fee_pct", "management_fee_pct", "is_enabled")


class Inline(admin.TabularInline):
    extra = 0


class UseInline(Inline):
    model = UseOfFunds


class ImageInline(Inline):
    model = ProjectImage


class DocInline(Inline):
    model = ProjectDocument
    fields = ("kind", "title", "visible_to_investors", "verified")
    readonly_fields = ("kind", "title")


class MonthInline(Inline):
    model = BoutiqueMonth


class ProductInline(Inline):
    model = BoutiqueProduct


class InstallmentInline(Inline):
    model = Installment
    readonly_fields = ("number", "due_date", "principal", "margin", "status", "paid_at")
    can_delete = False


class BoutiqueInline(admin.StackedInline):
    model = BoutiqueProfile
    extra = 0


class CompanyInline(admin.StackedInline):
    model = CompanyPlan
    extra = 0


class DealInline(admin.StackedInline):
    model = DealPlan
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "reference", "owner", "kind", "financing_model", "status", "target_amount",
                    "raised_amount", "risk_grade", "campaign_end")
    list_filter = ("status", "kind", "financing_model", "risk_grade", "wilaya", "sector")
    search_fields = ("title", "reference", "owner__phone", "owner__full_name", "boutique__shop_name")
    readonly_fields = ("reference", "slug", "shares_sold", "raised_amount", "investors_count", "views_count",
                       "review_fee_paid", "success_fee_pct", "management_fee_pct", "submitted_at", "funded_at",
                       "released_at", "closed_at")
    inlines = [BoutiqueInline, CompanyInline, DealInline, UseInline, MonthInline, ProductInline, ImageInline,
               DocInline, InstallmentInline]
    actions = ["release"]

    @admin.action(description=_("Libérer les fonds (projets financés)"))
    def release(self, request, queryset):
        for p in queryset.filter(status=Project.Status.FUNDED):
            try:
                release_funds(p, by=request.user)
                messages.success(request, _("Fonds libérés : %(p)s") % {"p": p})
            except InvestmentError as e:
                messages.error(request, f"{p}: {e}")


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    fields = ("order", "code", "text_fr", "text_ar", "type", "applies_to", "required", "is_public", "active")


@admin.register(QuestionSection)
class QuestionSectionAdmin(admin.ModelAdmin):
    list_display = ("title_fr", "title_ar", "order")
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("code", "text_fr", "section", "type", "applies_to", "required", "active")
    list_filter = ("section", "type", "required", "active")
    search_fields = ("code", "text_fr", "text_ar")


@admin.register(FinancialReport)
class FinancialReportAdmin(admin.ModelAdmin):
    list_display = ("project", "period_start", "revenue", "net_profit", "status", "submitted_at", "due_date")
    list_filter = ("status",)


for m in (ProjectAnswer, ProjectUpdate, ProjectQuestion, TeamMember, ProjectionYear, Milestone, Installment):
    admin.site.register(m)
