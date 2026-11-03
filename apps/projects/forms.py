from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.core.models import Moughataa, Wilaya
from apps.core.widgets import DateInput, MoneyInput, MonthInput, MoughataaSelect

from .models import (BoutiqueMonth, BoutiqueProduct, BoutiqueProfile, CompanyPlan, DealPlan, FinancialReport, Kind,
                     FinancingModel, Milestone, Project, ProjectDocument, ProjectionYear, ProjectQuestion,
                     ProjectUpdate, Question, Sector, TeamMember, UseOfFunds)


class StartForm(forms.Form):
    kind = forms.ChoiceField(label=_("Que voulez-vous financer ?"), choices=Kind.choices, widget=forms.RadioSelect)
    financing_model = forms.ChoiceField(label=_("Comment rémunérer les investisseurs ?"),
                                        choices=FinancingModel.choices, widget=forms.RadioSelect)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only project types with at least one open fee grid are offered. To pause or reopen a type
        # (e.g. boutiques), tick "ouvert aux nouvelles demandes" in Administration › Grilles tarifaires.
        from .models import FeePolicy

        open_kinds = set(FeePolicy.objects.filter(is_enabled=True).values_list("kind", flat=True))
        self.fields["kind"].choices = [(k, label) for k, label in Kind.choices if k in open_kinds]

    def clean(self):
        d = super().clean()
        if d.get("kind") == Kind.COMPANY and d.get("financing_model") == FinancingModel.MOURABAHA:
            raise forms.ValidationError(_(
                "Une entreprise se finance en Moucharaka (partage des bénéfices) : choisissez la Moucharaka."))
        return d


class BasicsForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["title", "tagline", "description", "sector", "wilaya", "moughataa", "neighborhood", "cover", "video_url"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 8}),
            "moughataa": MoughataaSelect(attrs={"data-depends-on": "wilaya"}),
            "cover": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["moughataa"].queryset = Moughataa.objects.select_related("wilaya")
        self.fields["description"].help_text = _(
            "Qui êtes-vous, que faites-vous, pourquoi maintenant, ce que les investisseurs gagnent.")

    def clean(self):
        d = super().clean()
        w, m = d.get("wilaya"), d.get("moughataa")
        if w and m and m.wilaya_id != w.pk:
            self.add_error("moughataa", _("Cette moughataa n'appartient pas à la wilaya choisie."))
        return d


class TermsForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["target_amount", "share_price", "min_shares", "min_funding_pct", "owner_contribution",
                  "campaign_days", "duration_months",
                  "investor_profit_share_pct", "projected_annual_return_pct", "distribution_frequency", "exit_mode",
                  "margin_pct", "repayment_mode", "guarantee", "report_frequency"]
        widgets = {"target_amount": MoneyInput(), "share_price": MoneyInput(), "owner_contribution": MoneyInput(),
                   "guarantee": forms.Textarea(attrs={"rows": 3})}

    MOUCHARAKA_FIELDS = ["investor_profit_share_pct", "projected_annual_return_pct", "distribution_frequency", "exit_mode"]
    MOURABAHA_FIELDS = ["margin_pct", "repayment_mode", "guarantee"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        p = self.instance
        drop = self.MOURABAHA_FIELDS if p.is_moucharaka else self.MOUCHARAKA_FIELDS
        for f in drop:
            self.fields.pop(f, None)
        for f in (self.MOUCHARAKA_FIELDS if p.is_moucharaka else self.MOURABAHA_FIELDS):
            self.fields[f].required = True
        self.fields["share_price"].help_text = _("Prix d'une part. Un prix bas permet à plus de personnes de participer.")
        self.fields["campaign_days"].widget.attrs["max"] = 60

    def clean(self):
        d = super().clean()
        target, price = d.get("target_amount"), d.get("share_price")
        if target and price:
            if price <= 0 or target % price:
                self.add_error("target_amount", _("Le montant doit être un multiple de la valeur d'une part."))
            if target / price < 10:
                self.add_error("share_price", _("Il faut au moins 10 parts : baissez la valeur de la part."))
        margin, months = d.get("margin_pct"), d.get("duration_months")
        if margin and months and margin * 12 / months > 40:
            self.add_error("margin_pct", _("Marge annualisée supérieure à 40 % : elle serait refusée à l'étude."))
        share = d.get("investor_profit_share_pct")
        if share is not None and not Decimal("5") <= share <= Decimal("90"):
            self.add_error("investor_profit_share_pct", _("Entre 5 % et 90 %."))
        if d.get("campaign_days") and d["campaign_days"] > 60:
            self.add_error("campaign_days", _("60 jours maximum."))
        return d


class BoutiqueForm(forms.ModelForm):
    class Meta:
        model = BoutiqueProfile
        exclude = ["project"]
        widgets = {
            "opened_on": DateInput(), "lease_end": DateInput(),
            "opening_time": forms.TimeInput(attrs={"type": "time"}),
            "closing_time": forms.TimeInput(attrs={"type": "time"}),
            "latitude": forms.HiddenInput(), "longitude": forms.HiddenInput(),
            "main_suppliers": forms.Textarea(attrs={"rows": 2}), "seasonality": forms.Textarea(attrs={"rows": 2}),
            "growth_plan": forms.Textarea(attrs={"rows": 3}),
            **{f: MoneyInput() for f in ["monthly_rent", "average_basket", "salaries", "owner_draw", "utilities",
                                         "transport", "taxes", "other_costs", "inventory_value", "equipment_value",
                                         "cash_on_hand", "customer_credit", "supplier_debt", "other_debt"]},
        }

    fieldsets = [
        (_("La boutique"), ["shop_name", "category", "opened_on", "premises", "monthly_rent", "lease_end",
                            "surface_m2", "storage_m2", "location_type", "landmark", "competitors_nearby",
                            "latitude", "longitude"]),
        (_("Fonctionnement"), ["opening_time", "closing_time", "days_open", "staff_count", "owner_works_in_shop",
                               "customers_per_day", "average_basket", "restock_frequency_days"]),
        (_("Marges et charges mensuelles"), ["gross_margin_pct", "salaries", "owner_draw", "utilities", "transport",
                                             "taxes", "other_costs"]),
        (_("Ce que possède et doit la boutique aujourd'hui"), ["inventory_value", "equipment_value", "cash_on_hand",
                                                              "customer_credit", "supplier_debt", "other_debt"]),
        (_("Ventes et approvisionnement"), ["cash_sales_pct", "mobile_money_pct", "credit_sales_pct",
                                            "main_suppliers", "supply_origin"]),
        (_("Formalisation et équipement"), ["has_trade_register", "keeps_books", "has_bank_account", "energy",
                                            "has_fridge", "insured"]),
        (_("Le projet"), ["seasonality", "growth_plan", "expected_revenue_uplift_pct"]),
    ]

    def clean(self):
        d = super().clean()
        mix = sum((d.get(f) or 0) for f in ("cash_sales_pct", "mobile_money_pct", "credit_sales_pct"))
        if mix and abs(mix - 100) > 1:
            self.add_error("credit_sales_pct", _("Espèces + mobile money + crédit doit faire 100 %."))
        if d.get("premises") == "rented" and not d.get("monthly_rent"):
            self.add_error("monthly_rent", _("Indiquez le loyer."))
        if (d.get("expected_revenue_uplift_pct") or 0) > 100:
            self.add_error("expected_revenue_uplift_pct", _("Une hausse de plus de 100 % n'est pas crédible sans justification."))
        return d

    def iter_fieldsets(self):
        for title, names in self.fieldsets:
            yield title, [self[n] for n in names if n not in ("latitude", "longitude")]


class CompanyForm(forms.ModelForm):
    class Meta:
        model = CompanyPlan
        exclude = ["project"]
        widgets = {"planned_launch": DateInput(),
                   **{f: forms.Textarea(attrs={"rows": 3}) for f in [
                       "problem", "solution", "target_customers", "market_size", "competitors", "advantage",
                       "revenue_model", "go_to_market", "licences_needed", "key_risks"]}}


class DealForm(forms.ModelForm):
    class Meta:
        model = DealPlan
        exclude = ["project"]
        widgets = {"goods_description": forms.Textarea(attrs={"rows": 3}),
                   "buyer_details": forms.Textarea(attrs={"rows": 2}), "collateral": forms.Textarea(attrs={"rows": 2}),
                   **{f: MoneyInput() for f in ["purchase_cost", "other_costs", "expected_sale_value", "collateral_value"]}}

    def clean(self):
        d = super().clean()
        if d.get("expected_sale_value") and d.get("purchase_cost") and d["expected_sale_value"] <= d["purchase_cost"]:
            self.add_error("expected_sale_value", _("La revente doit dépasser le coût d'achat."))
        return d


def _fs(model, fields, extra, widgets=None, min_num=0):
    return inlineformset_factory(Project, model, fields=fields, extra=extra, can_delete=True, widgets=widgets or {},
                                 min_num=min_num, validate_min=False)


MonthFormSet = _fs(BoutiqueMonth, ["month", "revenue", "purchases"], 0,
                   {"month": MonthInput(), "revenue": MoneyInput(), "purchases": MoneyInput()})
ProductFormSet = _fs(BoutiqueProduct, ["name", "unit", "buy_price", "sell_price", "monthly_units"], 3,
                     {"buy_price": MoneyInput(), "sell_price": MoneyInput()})
TeamFormSet = _fs(TeamMember, ["name", "role", "years_experience", "background", "full_time"], 2,
                  {"background": forms.Textarea(attrs={"rows": 2})})
ProjectionFormSet = _fs(ProjectionYear, ["year", "revenue", "expenses", "capex"], 3,
                        {"revenue": MoneyInput(), "expenses": MoneyInput(), "capex": MoneyInput()})
MilestoneFormSet = _fs(Milestone, ["title", "due_date", "budget"], 2, {"due_date": DateInput(), "budget": MoneyInput()})
UseOfFundsFormSet = _fs(UseOfFunds, ["category", "label", "amount"], 3, {"amount": MoneyInput()})


class MonthField(forms.DateField):
    """Accepts YYYY-MM from <input type=month>."""

    input_formats = ["%Y-%m", "%Y-%m-%d"]


for _fsc in (MonthFormSet,):
    _fsc.form.base_fields["month"] = MonthField(label=_("mois"), widget=MonthInput())


class QuestionnaireForm(forms.Form):
    def __init__(self, project, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        answers = {a.question_id: a.value for a in project.answers.all()}
        self.questions = [q for q in Question.objects.filter(active=True).select_related("section")
                          if q.applies(project.kind)]
        for q in self.questions:
            name = f"q_{q.pk}"
            kw = {"label": q.text, "help_text": q.help, "required": q.required, "initial": answers.get(q.pk)}
            if q.type == "textarea":
                f = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), **kw)
            elif q.type == "number":
                f = forms.DecimalField(**kw)
            elif q.type == "money":
                f = forms.DecimalField(widget=MoneyInput(), **kw)
            elif q.type == "choice":
                f = forms.ChoiceField(choices=[("", "—")] + q.localized_choices(), **kw)
            elif q.type == "multi":
                f = forms.MultipleChoiceField(choices=q.localized_choices(), widget=forms.CheckboxSelectMultiple, **kw)
            elif q.type == "bool":
                kw["required"] = False
                f = forms.TypedChoiceField(choices=[("", "—"), ("1", _("Oui")), ("0", _("Non"))],
                                           coerce=lambda v: v == "1", empty_value=None, **kw)
                f.initial = {True: "1", False: "0"}.get(kw["initial"], "")
            elif q.type == "date":
                f = forms.DateField(widget=DateInput(), **kw)
            else:
                f = forms.CharField(max_length=300, **kw)
            f.section = q.section
            self.fields[name] = f

    def sections(self):
        grouped = {}
        for q in self.questions:
            grouped.setdefault(q.section, []).append(self[f"q_{q.pk}"])
        return list(grouped.items())

    def save(self):
        from .models import ProjectAnswer

        for q in self.questions:
            value = self.cleaned_data.get(f"q_{q.pk}")
            if isinstance(value, Decimal):
                value = str(value)
            elif hasattr(value, "isoformat"):
                value = value.isoformat()
            ProjectAnswer.objects.update_or_create(project=self.project, question=q, defaults={"value": value})


class ImagesForm(forms.Form):
    images = forms.ImageField(label=_("Photos (boutique, stock, devanture…)"), required=False,
                              widget=forms.ClearableFileInput(attrs={"accept": "image/*"}))


class DocumentForm(forms.ModelForm):
    """Optional supporting documents. Type and title are optional: the upload starts as soon as a file is chosen."""

    class Meta:
        model = ProjectDocument
        fields = ["kind", "title", "visible_to_investors", "file"]
        widgets = {"file": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf",
                                                            "data-autosubmit": "doc"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].required = False
        self.fields["title"].required = False
        self.fields["file"].help_text = _("Le fichier est ajouté dès que vous le choisissez.")

    def clean(self):
        d = super().clean()
        if not d.get("kind"):
            d["kind"] = "other"
            self.instance.kind = "other"
        if not d.get("title") and d.get("file"):
            name = d["file"].name.rsplit("/", 1)[-1]
            d["title"] = (name.rsplit(".", 1)[0] or name)[:140]
            self.instance.title = d["title"]
        return d


class InvestForm(forms.Form):
    shares = forms.IntegerField(label=_("Nombre de parts"), min_value=1)
    risk = forms.BooleanField(label=_(
        "J'ai compris que mon capital n'est pas garanti, que les rendements sont estimés et que je peux perdre tout ou partie de ma mise."))


class ReportForm(forms.ModelForm):
    class Meta:
        model = FinancialReport
        fields = ["revenue", "cogs", "expenses", "inventory_value", "cash_balance", "customer_credit", "notes", "attachment"]
        widgets = {f: MoneyInput() for f in ["revenue", "cogs", "expenses", "inventory_value", "cash_balance",
                                             "customer_credit"]}


class UpdateForm(forms.ModelForm):
    class Meta:
        model = ProjectUpdate
        fields = ["title", "body", "image"]
        widgets = {"body": forms.Textarea(attrs={"rows": 4})}


class QuestionForm(forms.ModelForm):
    class Meta:
        model = ProjectQuestion
        fields = ["question"]
        widgets = {"question": forms.Textarea(attrs={"rows": 2})}


class BuybackForm(forms.Form):
    shares = forms.IntegerField(label=_("Parts à racheter"), min_value=1)
    price = forms.DecimalField(label=_("Prix par part (MRU)"), min_value=1, widget=MoneyInput())


class FilterForm(forms.Form):
    q = forms.CharField(required=False, label=_("Rechercher"))
    kind = forms.ChoiceField(required=False, choices=[("", _("Tous les types"))] + list(Kind.choices))
    model = forms.ChoiceField(required=False, choices=[("", _("Tous les modes"))] + list(FinancingModel.choices))
    status = forms.ChoiceField(required=False, choices=[
        ("", _("Ouverts et en activité")), ("funding", _("Collecte en cours")), ("active", _("En activité")),
        ("completed", _("Terminés")), ("all", _("Tous"))])
    wilaya = forms.ModelChoiceField(queryset=Wilaya.objects.all(), required=False, empty_label=_("Toutes les wilayas"))
    sector = forms.ModelChoiceField(queryset=Sector.objects.all(), required=False, empty_label=_("Tous les secteurs"))
    sort = forms.ChoiceField(required=False, choices=[
        ("new", _("Plus récents")), ("ending", _("Se terminent bientôt")), ("progress", _("Presque financés")),
        ("return", _("Rendement estimé"))])
