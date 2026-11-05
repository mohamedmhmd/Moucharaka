import uuid
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import private_storage, validate_document
from apps.core.models import Bilingual, TimeStamped

ZERO = Decimal("0")
MONEY = dict(max_digits=14, decimal_places=2)
PCT = dict(max_digits=6, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)])


class Sector(Bilingual):
    slug = models.SlugField(unique=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name_fr"]
        verbose_name = _("secteur")
        verbose_name_plural = _("secteurs")


class Kind(models.TextChoices):
    BOUTIQUE = "boutique", _("Boutique / commerce en activité")
    DEAL = "deal", _("Opération ponctuelle")
    COMPANY = "company", _("Entreprise existante ou en création")


class FinancingModel(models.TextChoices):
    MOUCHARAKA = "moucharaka", _("Moucharaka — partage des bénéfices")
    MOURABAHA = "mourabaha", _("Mourabaha — marge fixe convenue")


class FeePolicy(models.Model):
    """Commercial terms per (project kind, financing model).

    The values are copied onto each project when it is approved, so changing a
    policy never alters a live contract.
    """

    kind = models.CharField(_("type de projet"), max_length=10, choices=Kind.choices)
    financing_model = models.CharField(_("mode de financement"), max_length=12, choices=FinancingModel.choices)
    review_fee = models.DecimalField(_("frais d'étude du dossier (MRU)"), **MONEY, default=Decimal("100"))
    success_fee_pct = models.DecimalField(_("commission de succès (% des fonds levés)"), **PCT, default=Decimal("5"))
    management_fee_pct = models.DecimalField(
        _("commission de gestion (% des bénéfices / marges distribués)"), **PCT, default=Decimal("8"))
    min_target = models.DecimalField(_("montant minimum"), **MONEY, default=Decimal("50000"))
    max_target = models.DecimalField(_("montant maximum"), **MONEY, default=Decimal("5000000"))
    is_enabled = models.BooleanField(_("ouvert aux nouvelles demandes"), default=True)

    class Meta:
        unique_together = [("kind", "financing_model")]
        verbose_name = _("grille tarifaire")
        verbose_name_plural = _("grilles tarifaires")

    def __str__(self):
        return f"{self.get_kind_display()} / {self.get_financing_model_display()}"

    @classmethod
    def for_project(cls, project):
        return cls.objects.filter(kind=project.kind, financing_model=project.financing_model).first() or cls(
            kind=project.kind, financing_model=project.financing_model)


class Project(TimeStamped):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        SUBMITTED = "submitted", _("En cours d'étude")
        CHANGES = "changes", _("Corrections demandées")
        REJECTED = "rejected", _("Refusé")
        FUNDING = "funding", _("Collecte en cours")
        FUNDED = "funded", _("Objectif atteint")
        ACTIVE = "active", _("En activité")
        COMPLETED = "completed", _("Terminé")
        FAILED = "failed", _("Collecte échouée")
        DEFAULTED = "defaulted", _("En défaut")
        CANCELLED = "cancelled", _("Annulé")

    PUBLIC_STATUSES = ["funding", "funded", "active", "completed", "failed", "defaulted"]
    EDITABLE_STATUSES = ["draft", "changes"]

    class Frequency(models.TextChoices):
        MONTHLY = "monthly", _("Mensuelle")
        QUARTERLY = "quarterly", _("Trimestrielle")
        SEMIANNUAL = "semiannual", _("Semestrielle")
        ANNUAL = "annual", _("Annuelle")
        AT_EXIT = "at_exit", _("À la sortie")

    class Exit(models.TextChoices):
        DIMINISHING = "diminishing", _("Rachat progressif des parts par le porteur (Moucharaka moutanaqisa)")
        BUYBACK_END = "buyback_end", _("Rachat de toutes les parts à l'échéance")
        SALE = "sale", _("Vente de l'activité et partage du produit")
        OPEN = "open", _("Sans échéance : parts revendables sur le marché")

    class Repayment(models.TextChoices):
        BULLET = "bullet", _("En une fois à l'échéance")
        MONTHLY = "monthly", _("Échéances mensuelles")
        QUARTERLY = "quarterly", _("Échéances trimestrielles")

    RISK_GRADES = [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E")]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="projects",
                              verbose_name=_("porteur"))
    slug = models.SlugField(max_length=80, unique=True, editable=False)
    reference = models.CharField(max_length=12, unique=True, editable=False)
    kind = models.CharField(_("type de projet"), max_length=10, choices=Kind.choices)
    financing_model = models.CharField(_("mode de financement"), max_length=12, choices=FinancingModel.choices)
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)

    title = models.CharField(_("nom du projet"), max_length=120)
    tagline = models.CharField(_("résumé en une phrase"), max_length=200, blank=True)
    description = models.TextField(_("présentation détaillée"), blank=True)
    sector = models.ForeignKey(Sector, on_delete=models.PROTECT, verbose_name=_("secteur"), null=True, blank=True)
    wilaya = models.ForeignKey("core.Wilaya", on_delete=models.PROTECT, verbose_name=_("wilaya"), null=True, blank=True)
    moughataa = models.ForeignKey("core.Moughataa", on_delete=models.PROTECT, verbose_name=_("moughataa"),
                                  null=True, blank=True)
    neighborhood = models.CharField(_("quartier"), max_length=120, blank=True)
    cover = models.ImageField(_("photo principale"), upload_to="projects/covers/", blank=True)
    video_url = models.URLField(_("lien vidéo (facultatif)"), blank=True)

    # Funding terms
    target_amount = models.DecimalField(_("montant recherché (MRU)"), **MONEY)
    share_price = models.DecimalField(_("valeur d'une part (MRU)"), **MONEY, default=Decimal("1000"))
    min_shares = models.PositiveIntegerField(_("parts minimum par investisseur"), default=1)
    min_funding_pct = models.DecimalField(
        _("seuil de réussite (% de l'objectif)"), **PCT, default=Decimal("100"),
        help_text=_("Si la collecte atteint ce seuil à la date limite, le projet est financé avec le montant collecté."))
    owner_contribution = models.DecimalField(_("apport personnel du porteur (MRU)"), **MONEY, default=ZERO)
    campaign_days = models.PositiveSmallIntegerField(_("durée de la collecte (jours)"), default=30)
    duration_months = models.PositiveSmallIntegerField(_("durée du financement (mois)"), default=12)

    # Moucharaka terms
    investor_profit_share_pct = models.DecimalField(
        _("part des bénéfices revenant aux investisseurs (%)"), **PCT, null=True, blank=True)
    projected_annual_return_pct = models.DecimalField(
        _("rendement potentiel (%), non garanti"), **PCT, null=True, blank=True)
    distribution_frequency = models.CharField(_("fréquence des distributions"), max_length=12,
                                              choices=Frequency.choices, default=Frequency.QUARTERLY)
    exit_mode = models.CharField(_("sortie des investisseurs"), max_length=12, choices=Exit.choices, blank=True)
    # Mourabaha terms
    margin_pct = models.DecimalField(_("marge convenue sur la durée (%)"), **PCT, null=True, blank=True)
    repayment_mode = models.CharField(_("remboursement"), max_length=10, choices=Repayment.choices, blank=True)
    guarantee = models.TextField(_("garanties proposées"), blank=True,
                                 help_text=_("Caution personnelle, nantissement du stock, garant, chèque de garantie…"))
    report_frequency = models.CharField(_("fréquence des rapports financiers"), max_length=12,
                                        choices=Frequency.choices[:2], default=Frequency.MONTHLY)

    # Fee snapshot (copied from FeePolicy at approval)
    review_fee_paid = models.DecimalField(**MONEY, default=ZERO, editable=False)
    success_fee_pct = models.DecimalField(**PCT, default=ZERO, editable=False)
    management_fee_pct = models.DecimalField(**PCT, default=ZERO, editable=False)

    # Live counters
    shares_sold = models.PositiveIntegerField(default=0, editable=False)
    raised_amount = models.DecimalField(**MONEY, default=ZERO, editable=False)
    investors_count = models.PositiveIntegerField(default=0, editable=False)
    views_count = models.PositiveIntegerField(default=0, editable=False)

    # Review & lifecycle
    risk_grade = models.CharField(_("note de risque"), max_length=1, choices=RISK_GRADES, blank=True)
    review_notes = models.TextField(_("avis de l'équipe (public)"), blank=True)
    internal_notes = models.TextField(_("notes internes"), blank=True)
    changes_requested = models.TextField(_("corrections demandées"), blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    campaign_start = models.DateTimeField(null=True, blank=True)
    campaign_end = models.DateTimeField(null=True, blank=True)
    funded_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    trading_enabled = models.BooleanField(_("revente des parts autorisée"), default=True)
    preview_token = models.CharField(max_length=24, blank=True, editable=False, db_index=True,
                                     help_text=_("Clé du lien d'aperçu privé (projet pas encore publié)."))
    shares_count = models.PositiveIntegerField(default=0, editable=False, help_text=_("Ouvertures du lien partagé."))
    featured_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("projet")
        verbose_name_plural = _("projets")
        indexes = [models.Index(fields=["status", "kind"])]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = "MP-" + uuid.uuid4().hex[:6].upper()
        if not self.preview_token:
            import secrets

            self.preview_token = secrets.token_urlsafe(12)
        if not self.slug:
            base = slugify(self.title, allow_unicode=False)[:60] or "projet"
            self.slug = f"{base}-{self.reference[3:].lower()}"
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("projects:detail", args=[self.slug])

    def get_share_path(self, private=False):
        """Short link built from the project ID, e.g. /s/MP-3FA9C1/.
        `private=True` adds the preview key so a draft can be shown before publication."""
        path = reverse("short", args=[self.reference])
        return f"{path}?k={self.preview_token}" if private and not self.is_public else path

    # ---------------------------------------------------------- derived values
    @property
    def place(self):
        """"Quartier, Moughataa, Wilaya" with whatever the owner filled in."""
        parts = [self.neighborhood, getattr(self.moughataa, "name", ""), getattr(self.wilaya, "name", "")]
        return ", ".join(p for p in parts if p)

    @property
    def total_shares(self):
        if not self.share_price:
            return 0
        return int(self.target_amount // self.share_price)

    @property
    def shares_available(self):
        return max(self.total_shares - self.shares_sold, 0)

    @property
    def funding_pct(self):
        if not self.target_amount:
            return 0
        return min(int(self.raised_amount * 100 / self.target_amount), 100)

    @property
    def days_left(self):
        if not self.campaign_end:
            return None
        return max((self.campaign_end - timezone.now()).days, 0)

    @property
    def is_deal(self):
        """Opération ponctuelle: investors put in an amount, the owner pays everything back once."""
        return self.kind == Kind.DEAL

    @property
    def is_moucharaka(self):
        return self.financing_model == FinancingModel.MOUCHARAKA

    @property
    def is_mourabaha(self):
        return self.financing_model == FinancingModel.MOURABAHA

    @property
    def is_public(self):
        return self.status in self.PUBLIC_STATUSES

    @property
    def is_editable(self):
        return self.status in self.EDITABLE_STATUSES

    @property
    def is_tradable(self):
        return self.trading_enabled and self.status == self.Status.ACTIVE and not self.is_deal

    @property
    def funded_base(self):
        """Capital actually raised (after a partially successful campaign)."""
        return self.raised_amount if self.status not in ("draft", "submitted", "changes", "funding") else self.target_amount

    @property
    def margin_amount(self):
        if self.margin_pct is None:
            return ZERO
        return (self.funded_base * self.margin_pct / 100).quantize(Decimal("0.01"))

    @property
    def mourabaha_annualized_pct(self):
        if not self.margin_pct or not self.duration_months:
            return None
        return (self.margin_pct * 12 / self.duration_months).quantize(Decimal("0.1"))

    @property
    def distributions_total(self):
        return self.distributions.filter(status="paid").aggregate(s=Sum("net_amount"))["s"] or ZERO

    @property
    def last_trade_price(self):
        t = self.trades.order_by("-created_at").first() if hasattr(self, "trades") else None
        return t.price_per_share if t else None

    def headline_return(self):
        """Indicative annual figure for listings, labelled differently per model."""
        if self.is_mourabaha:
            return self.mourabaha_annualized_pct
        return self.projected_annual_return_pct


class ProjectImage(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(_("photo"), upload_to="projects/gallery/")
    caption = models.CharField(_("légende"), max_length=140, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class ProjectDocument(models.Model):
    KINDS = [
        ("registration", _("Registre du commerce / patente")),
        ("nif", _("Numéro d'identification fiscale")),
        ("lease", _("Contrat de bail")),
        ("ownership", _("Titre de propriété / attestation")),
        ("invoice", _("Facture pro forma / devis")),
        ("purchase_order", _("Bon de commande client")),
        ("statement", _("Relevé bancaire / mobile money")),
        ("accounts", _("Cahier de comptes / états financiers")),
        ("guarantee", _("Acte de garantie / caution")),
        ("license", _("Autorisation / licence")),
        ("other", _("Autre")),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(_("type"), max_length=16, choices=KINDS)
    title = models.CharField(_("intitulé"), max_length=140)
    file = models.FileField(_("fichier"), upload_to="projects/docs/", storage=private_storage,
                            validators=[validate_document])
    visible_to_investors = models.BooleanField(_("visible par les investisseurs vérifiés"), default=True)
    verified = models.BooleanField(_("vérifié par l'équipe"), default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "id"]


class UseOfFunds(models.Model):
    CATEGORIES = [
        ("stock", _("Achat de marchandises")),
        ("equipment", _("Équipement (frigo, étagères, balance…)")),
        ("renovation", _("Aménagement / travaux")),
        ("energy", _("Énergie (solaire, groupe)")),
        ("vehicle", _("Transport / véhicule")),
        ("working_capital", _("Fonds de roulement")),
        ("rent", _("Loyer / caution")),
        ("licences", _("Formalités, licences")),
        ("marketing", _("Marketing")),
        ("other", _("Autre")),
    ]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="uses_of_funds")
    category = models.CharField(_("catégorie"), max_length=16, choices=CATEGORIES)
    label = models.CharField(_("détail"), max_length=140)
    amount = models.DecimalField(_("montant (MRU)"), **MONEY)

    class Meta:
        ordering = ["-amount"]


# ---------------------------------------------------------------- Boutique


class BoutiqueProfile(models.Model):
    CATEGORIES = [
        ("grocery", _("Alimentation générale (boutique de quartier)")),
        ("wholesale", _("Demi-gros / grossiste")),
        ("hardware", _("Quincaillerie")),
        ("building", _("Matériaux de construction")),
        ("phones", _("Téléphones, accessoires, transfert d'argent")),
        ("textile", _("Tissus, melhfa, voiles, habillement")),
        ("cosmetics", _("Cosmétiques, parfums, encens")),
        ("butcher", _("Boucherie")),
        ("bakery", _("Boulangerie / pâtisserie")),
        ("restaurant", _("Restaurant / fast-food")),
        ("appliances", _("Électroménager / électronique")),
        ("autoparts", _("Pièces auto")),
        ("stationery", _("Librairie / fournitures scolaires")),
        ("gas", _("Gaz, charbon, eau")),
        ("other", _("Autre commerce")),
    ]
    PREMISES = [("rented", _("Loué")), ("owned", _("Propriété")), ("family", _("Local familial (sans loyer)"))]
    LOCATIONS = [("main_road", _("Sur une grande route")), ("market", _("Dans un marché")),
                 ("residential", _("Rue de quartier résidentiel")), ("mall", _("Centre commercial"))]
    ENERGY = [("somelec", _("Réseau SOMELEC")), ("solar", _("Solaire")), ("generator", _("Groupe électrogène")),
              ("mixed", _("Mixte")), ("none", _("Pas d'électricité"))]

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="boutique")
    shop_name = models.CharField(_("enseigne / nom de la boutique"), max_length=120)
    category = models.CharField(_("activité"), max_length=12, choices=CATEGORIES)
    opened_on = models.DateField(_("date d'ouverture"), null=True, blank=True)
    # Premises & location
    premises = models.CharField(_("local"), max_length=8, choices=PREMISES)
    monthly_rent = models.DecimalField(_("loyer mensuel (MRU)"), **MONEY, default=ZERO)
    lease_end = models.DateField(_("fin du bail"), null=True, blank=True)
    surface_m2 = models.PositiveIntegerField(_("surface de vente (m²)"))
    storage_m2 = models.PositiveIntegerField(_("surface de stockage (m²)"), default=0)
    location_type = models.CharField(_("emplacement"), max_length=12, choices=LOCATIONS)
    landmark = models.CharField(_("repère"), max_length=160, blank=True, help_text=_("Ex : en face de la mosquée, carrefour Madrid…"))
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    competitors_nearby = models.PositiveSmallIntegerField(_("boutiques similaires à moins de 500 m"), default=0)
    # Operations
    opening_time = models.TimeField(_("ouverture"), null=True, blank=True)
    closing_time = models.TimeField(_("fermeture"), null=True, blank=True)
    days_open = models.PositiveSmallIntegerField(_("jours d'ouverture par semaine"), default=7,
                                                 validators=[MaxValueValidator(7)])
    staff_count = models.PositiveSmallIntegerField(_("employés (hors gérant)"), default=0)
    owner_works_in_shop = models.BooleanField(_("le porteur tient lui-même la boutique"), default=True)
    customers_per_day = models.PositiveIntegerField(_("clients par jour (moyenne)"))
    average_basket = models.DecimalField(_("panier moyen (MRU)"), **MONEY)
    # Margins & costs (monthly)
    gross_margin_pct = models.DecimalField(_("marge brute moyenne (%)"), **PCT,
                                           help_text=_("(Prix de vente − prix d'achat) ÷ prix de vente."))
    salaries = models.DecimalField(_("salaires mensuels (MRU)"), **MONEY, default=ZERO)
    owner_draw = models.DecimalField(_("rémunération du gérant (MRU / mois)"), **MONEY, default=ZERO)
    utilities = models.DecimalField(_("électricité, eau, téléphone (MRU / mois)"), **MONEY, default=ZERO)
    transport = models.DecimalField(_("transport, approvisionnement (MRU / mois)"), **MONEY, default=ZERO)
    taxes = models.DecimalField(_("patente, taxes communales (MRU / mois)"), **MONEY, default=ZERO)
    other_costs = models.DecimalField(_("autres charges (MRU / mois)"), **MONEY, default=ZERO)
    # Balance sheet snapshot
    inventory_value = models.DecimalField(_("valeur du stock actuel (MRU)"), **MONEY)
    equipment_value = models.DecimalField(_("valeur des équipements (MRU)"), **MONEY, default=ZERO)
    cash_on_hand = models.DecimalField(_("trésorerie disponible (MRU)"), **MONEY, default=ZERO)
    customer_credit = models.DecimalField(_("crédits accordés aux clients (MRU)"), **MONEY, default=ZERO,
                                          help_text=_("Ventes à crédit non encore payées (le « carnet »)."))
    supplier_debt = models.DecimalField(_("dettes fournisseurs (MRU)"), **MONEY, default=ZERO)
    other_debt = models.DecimalField(_("autres dettes / prêts (MRU)"), **MONEY, default=ZERO)
    # Sales mix
    cash_sales_pct = models.DecimalField(_("ventes en espèces (%)"), **PCT, default=Decimal("70"))
    mobile_money_pct = models.DecimalField(_("ventes par Bankily / Masrvi / Sedad (%)"), **PCT, default=Decimal("20"))
    credit_sales_pct = models.DecimalField(_("ventes à crédit (%)"), **PCT, default=Decimal("10"))
    # Supply
    main_suppliers = models.TextField(_("principaux fournisseurs"), blank=True)
    supply_origin = models.CharField(_("origine des marchandises"), max_length=200, blank=True,
                                     help_text=_("Ex : grossistes de Nouakchott, Dakar, Las Palmas, Dubaï, Chine…"))
    restock_frequency_days = models.PositiveSmallIntegerField(_("réapprovisionnement tous les (jours)"), default=7)
    # Formalisation & equipment
    has_trade_register = models.BooleanField(_("inscrite au registre du commerce / patente"), default=False)
    keeps_books = models.BooleanField(_("tient un cahier ou un logiciel de caisse"), default=False)
    has_bank_account = models.BooleanField(_("compte bancaire professionnel"), default=False)
    energy = models.CharField(_("électricité"), max_length=10, choices=ENERGY, default="somelec")
    has_fridge = models.BooleanField(_("réfrigérateur / congélateur"), default=False)
    insured = models.BooleanField(_("assurance (incendie, vol)"), default=False)
    # Plan
    seasonality = models.TextField(_("saisonnalité"), blank=True,
                                   help_text=_("Ramadan, Tabaski, rentrée scolaire, saison des pluies, hivernage…"))
    growth_plan = models.TextField(_("que changera le financement ?"))
    expected_revenue_uplift_pct = models.DecimalField(
        _("hausse attendue du chiffre d'affaires (%)"), max_digits=6, decimal_places=2, default=Decimal("20"))

    def __str__(self):
        return self.shop_name

    # --------------------------------------------------------------- model
    @property
    def fixed_costs(self):
        return (self.monthly_rent + self.salaries + self.owner_draw + self.utilities + self.transport + self.taxes
                + self.other_costs)

    @property
    def declared_monthly_revenue(self):
        """Average of declared monthly history, else traffic × basket × days."""
        agg = self.project.boutique_months.aggregate(s=Sum("revenue"), n=models.Count("id"))
        if agg["n"]:
            return (agg["s"] / agg["n"]).quantize(Decimal("1"))
        return (Decimal(self.customers_per_day) * self.average_basket * Decimal(self.days_open) * Decimal("4.33")).quantize(Decimal("1"))

    @property
    def traffic_based_revenue(self):
        return (Decimal(self.customers_per_day) * self.average_basket * Decimal(self.days_open) * Decimal("4.33")).quantize(Decimal("1"))

    def model(self, revenue_factor=Decimal("1"), apply_uplift=True):
        """Monthly P&L in MRU. `revenue_factor` drives the scenarios."""
        base_rev = self.declared_monthly_revenue
        uplift = (1 + self.expected_revenue_uplift_pct / 100) if apply_uplift else Decimal("1")
        revenue = (base_rev * uplift * revenue_factor).quantize(Decimal("1"))
        margin = self.gross_margin_pct / 100
        cogs = (revenue * (1 - margin)).quantize(Decimal("1"))
        gross = revenue - cogs
        fixed = self.fixed_costs
        net = gross - fixed
        project = self.project
        share = (project.investor_profit_share_pct or ZERO) / 100
        investors = max(net, ZERO) * share if project.is_moucharaka else ZERO
        capital = project.target_amount or Decimal("1")
        annual_yield = (investors * 12 * 100 / capital).quantize(Decimal("0.1")) if capital else ZERO
        return {
            "revenue": revenue, "cogs": cogs, "gross": gross, "fixed": fixed, "net": net,
            "investors": investors.quantize(Decimal("1")), "owner": (net - investors).quantize(Decimal("1")),
            "annual_yield": annual_yield,
        }

    def scenarios(self):
        return {
            "current": self.model(apply_uplift=False),
            "pessimistic": self.model(Decimal("0.80")),
            "base": self.model(),
            "optimistic": self.model(Decimal("1.15")),
        }

    def indicators(self):
        """Health ratios shown to investors with a plain-language verdict."""
        rev = self.declared_monthly_revenue or Decimal("1")
        margin = self.gross_margin_pct / 100 or Decimal("0.01")
        monthly_cogs = rev * (1 - margin)
        breakeven = (self.fixed_costs / margin).quantize(Decimal("1"))
        stock_days = int(self.inventory_value / (monthly_cogs / 30)) if monthly_cogs else 0
        traffic_gap = int((self.traffic_based_revenue - rev) * 100 / rev) if rev else 0
        return [
            {"key": "breakeven", "label": _("Chiffre d'affaires d'équilibre"), "value": breakeven, "unit": "MRU",
             "ok": breakeven < rev, "hint": _("Ventes mensuelles nécessaires pour couvrir toutes les charges.")},
            {"key": "safety", "label": _("Marge de sécurité"), "value": int((rev - breakeven) * 100 / rev), "unit": "%",
             "ok": rev > breakeven * Decimal("1.2"), "hint": _("De combien les ventes peuvent baisser avant de perdre de l'argent.")},
            {"key": "rent", "label": _("Poids du loyer"), "value": int(self.monthly_rent * 100 / rev), "unit": "%",
             "ok": self.monthly_rent <= rev * Decimal("0.10"), "hint": _("Loyer ÷ ventes. Au-delà de 10 %, le loyer pèse lourd.")},
            {"key": "stock", "label": _("Couverture du stock"), "value": stock_days, "unit": _("jours"),
             "ok": 7 <= stock_days <= 90, "hint": _("Nombre de jours de ventes couverts par le stock actuel.")},
            {"key": "credit", "label": _("Crédit clients"), "value": int(self.customer_credit * 100 / rev), "unit": "%",
             "ok": self.customer_credit <= rev * Decimal("0.25"), "hint": _("Ventes à crédit non payées ÷ ventes du mois.")},
            {"key": "consistency", "label": _("Cohérence fréquentation / ventes"), "value": traffic_gap, "unit": "%",
             "ok": abs(traffic_gap) <= 25, "hint": _("Écart entre ventes déclarées et clients × panier moyen.")},
        ]


class BoutiqueMonth(models.Model):
    """Declared history (before financing). Actuals come from FinancialReport."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="boutique_months")
    month = models.DateField(_("mois"))
    revenue = models.DecimalField(_("ventes (MRU)"), **MONEY)
    purchases = models.DecimalField(_("achats de marchandises (MRU)"), **MONEY, default=ZERO)

    class Meta:
        ordering = ["month"]
        unique_together = [("project", "month")]


class BoutiqueProduct(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="boutique_products")
    name = models.CharField(_("produit"), max_length=100)
    unit = models.CharField(_("unité"), max_length=30, blank=True, help_text=_("sac de 50 kg, carton, litre…"))
    buy_price = models.DecimalField(_("prix d'achat"), **MONEY)
    sell_price = models.DecimalField(_("prix de vente"), **MONEY)
    monthly_units = models.PositiveIntegerField(_("quantité vendue / mois"))

    class Meta:
        ordering = ["-monthly_units"]

    @property
    def margin_pct(self):
        if not self.sell_price:
            return ZERO
        return ((self.sell_price - self.buy_price) * 100 / self.sell_price).quantize(Decimal("0.1"))

    @property
    def monthly_sales(self):
        return self.sell_price * self.monthly_units

    @property
    def monthly_margin(self):
        return (self.sell_price - self.buy_price) * self.monthly_units


# ---------------------------------------------------------------- Future company


class CompanyPlan(models.Model):
    LEGAL_FORMS = [("ei", _("Entreprise individuelle")), ("sarl", "SARL"), ("suarl", "SARL unipersonnelle"),
                   ("sa", "SA"), ("gie", "GIE"), ("coop", _("Coopérative")), ("tbd", _("À définir"))]
    STAGES = [("idea", _("Idée")), ("prototype", _("Prototype / test")), ("first_sales", _("Premières ventes")),
              ("ready", _("Prêt à lancer"))]
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="company")
    legal_form = models.CharField(_("forme juridique"), max_length=6, choices=LEGAL_FORMS, blank=True)
    stage = models.CharField(_("stade d'avancement"), max_length=12, choices=STAGES, blank=True)
    is_registered = models.BooleanField(_("société déjà immatriculée"), default=False)
    rccm_number = models.CharField(_("numéro RCCM"), max_length=40, blank=True)
    nif = models.CharField(_("NIF"), max_length=30, blank=True)
    planned_launch = models.DateField(_("date de lancement prévue"), null=True, blank=True)
    problem = models.TextField(_("problème résolu"), blank=True)
    solution = models.TextField(_("solution / produit"), blank=True)
    target_customers = models.TextField(_("clients visés"), blank=True)
    market_size = models.TextField(_("taille du marché"), blank=True)
    competitors = models.TextField(_("concurrents"), blank=True)
    advantage = models.TextField(_("avantage concurrentiel"), blank=True)
    revenue_model = models.TextField(_("comment l'entreprise gagne de l'argent"), blank=True)
    go_to_market = models.TextField(_("plan commercial"), blank=True)
    licences_needed = models.TextField(_("autorisations nécessaires"), blank=True)
    key_risks = models.TextField(_("principaux risques et parades"), blank=True)
    breakeven_month = models.PositiveSmallIntegerField(_("mois d'atteinte de l'équilibre"), null=True, blank=True)
    jobs_created = models.PositiveSmallIntegerField(_("emplois créés"), default=0)
    investors_equity_pct = models.DecimalField(_("part du capital offerte aux investisseurs (%)"), **PCT,
                                               null=True, blank=True)


class TeamMember(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="team")
    name = models.CharField(_("nom"), max_length=120)
    role = models.CharField(_("rôle"), max_length=120)
    years_experience = models.PositiveSmallIntegerField(_("années d'expérience"), default=0)
    background = models.TextField(_("parcours"), blank=True)
    full_time = models.BooleanField(_("à plein temps"), default=True)


class ProjectionYear(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="projections")
    year = models.PositiveSmallIntegerField(_("année"), validators=[MinValueValidator(1), MaxValueValidator(5)])
    revenue = models.DecimalField(_("chiffre d'affaires"), **MONEY)
    expenses = models.DecimalField(_("charges"), **MONEY)
    capex = models.DecimalField(_("investissements"), **MONEY, default=ZERO)

    class Meta:
        ordering = ["year"]
        unique_together = [("project", "year")]

    @property
    def profit(self):
        return self.revenue - self.expenses


class Milestone(models.Model):
    STATUS = [("planned", _("Prévu")), ("done", _("Réalisé")), ("late", _("En retard"))]
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(_("étape"), max_length=140)
    due_date = models.DateField(_("échéance"))
    budget = models.DecimalField(_("budget"), **MONEY, default=ZERO)
    status = models.CharField(max_length=8, choices=STATUS, default="planned")
    completed_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["due_date"]


# ---------------------------------------------------------------- One-time deal


class DealPlan(models.Model):
    OPERATIONS = [
        ("stock", _("Achat de stock pour revente")),
        ("import", _("Importation de marchandises")),
        ("livestock", _("Bétail (moutons de Tabaski, embouche)")),
        ("dates", _("Récolte de dattes (guetna)")),
        ("fishing", _("Campagne de pêche")),
        ("agri", _("Campagne agricole")),
        ("contract", _("Exécution d'un marché / bon de commande")),
        ("equipment", _("Achat d'équipement productif")),
        ("other", _("Autre opération")),
    ]
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name="deal")
    operation = models.CharField(_("nature de l'opération"), max_length=10, choices=OPERATIONS, blank=True)
    goods_description = models.TextField(_("biens achetés (quantité, qualité)"), blank=True)
    supplier = models.CharField(_("fournisseur"), max_length=160, blank=True)
    purchase_cost = models.DecimalField(_("coût d'achat total (MRU)"), **MONEY, null=True, blank=True)
    other_costs = models.DecimalField(_("frais annexes : transport, douane, stockage (MRU)"), **MONEY, default=ZERO)
    expected_sale_value = models.DecimalField(_("valeur de revente attendue (MRU)"), **MONEY, null=True, blank=True)
    cycle_days = models.PositiveSmallIntegerField(_("durée du cycle (jours)"), null=True, blank=True)
    buyer_identified = models.BooleanField(_("acheteur déjà identifié"), default=False)
    buyer_details = models.TextField(_("acheteur / débouchés"), blank=True)
    has_purchase_order = models.BooleanField(_("bon de commande ou contrat signé"), default=False)
    collateral = models.TextField(_("sûretés"), blank=True)
    collateral_value = models.DecimalField(_("valeur des sûretés (MRU)"), **MONEY, default=ZERO)
    previous_cycles = models.PositiveSmallIntegerField(_("opérations similaires déjà réalisées"), default=0)

    @property
    def expected_profit(self):
        if self.expected_sale_value is None or self.purchase_cost is None:
            return None
        return self.expected_sale_value - self.purchase_cost - (self.other_costs or 0)

    @property
    def coverage_ratio(self):
        """Expected sale value ÷ (financing + margin owed). >1 = cushion."""
        owed = self.project.target_amount + self.project.margin_amount
        if not owed or self.expected_sale_value is None:
            return None
        return (self.expected_sale_value / owed).quantize(Decimal("0.01"))


# ---------------------------------------------------------------- Questionnaire


class QuestionSection(models.Model):
    title_fr = models.CharField(max_length=160)
    title_ar = models.CharField(max_length=160)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]
        verbose_name = _("section du questionnaire")

    @property
    def title(self):
        return self.title_ar if (get_language() or "").startswith("ar") else self.title_fr

    def __str__(self):
        return self.title_fr


class Question(models.Model):
    TYPES = [("text", _("Texte court")), ("textarea", _("Texte long")), ("number", _("Nombre")),
             ("money", _("Montant")), ("choice", _("Choix unique")), ("multi", _("Choix multiple")),
             ("bool", _("Oui / non")), ("date", _("Date"))]
    section = models.ForeignKey(QuestionSection, on_delete=models.CASCADE, related_name="questions")
    code = models.SlugField(unique=True)
    text_fr = models.CharField(max_length=300)
    text_ar = models.CharField(max_length=300)
    help_fr = models.CharField(max_length=300, blank=True)
    help_ar = models.CharField(max_length=300, blank=True)
    type = models.CharField(max_length=10, choices=TYPES, default="text")
    choices = models.JSONField(default=list, blank=True, help_text='[{"value": "x", "fr": "…", "ar": "…"}]')
    applies_to = models.CharField(max_length=60, default="boutique,deal,company",
                                  help_text=_("Types de projet concernés, séparés par des virgules."))
    required = models.BooleanField(default=False)
    is_public = models.BooleanField(_("réponse visible des investisseurs"), default=True)
    order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["section__order", "order"]
        verbose_name = _("question")

    def __str__(self):
        return self.text_fr

    def _ar(self):
        return (get_language() or "").startswith("ar")

    @property
    def text(self):
        return self.text_ar if self._ar() else self.text_fr

    @property
    def help(self):
        return self.help_ar if self._ar() else self.help_fr

    def localized_choices(self):
        key = "ar" if self._ar() else "fr"
        return [(c["value"], c.get(key) or c.get("fr")) for c in self.choices]

    def applies(self, kind):
        return kind in [k.strip() for k in self.applies_to.split(",")]


class ProjectAnswer(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    value = models.JSONField(null=True, blank=True)

    class Meta:
        unique_together = [("project", "question")]

    def display(self):
        v, q = self.value, self.question
        if v in (None, "", []):
            return "—"
        if q.type == "bool":
            return _("Oui") if v else _("Non")
        if q.type in ("choice", "multi"):
            labels = dict(q.localized_choices())
            vals = v if isinstance(v, list) else [v]
            return ", ".join(str(labels.get(x, x)) for x in vals)
        if q.type == "money":
            try:
                return f"{Decimal(str(v)):,.0f} MRU".replace(",", " ")
            except Exception:  # noqa: BLE001
                return str(v)
        return str(v)


# ---------------------------------------------------------------- Life of a funded project


class ProjectUpdate(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="updates")
    title = models.CharField(_("titre"), max_length=160)
    body = models.TextField(_("message"))
    image = models.ImageField(_("photo"), upload_to="projects/updates/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ProjectQuestion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="questions")
    asker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    question = models.TextField(_("votre question"))
    answer = models.TextField(_("réponse"), blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ProjectInterest(models.Model):
    """Someone who wants to invest once the campaign opens (shared link before launch)."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="interests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_interests")
    amount = models.DecimalField(_("montant envisagé (MRU)"), **MONEY, null=True, blank=True)
    note = models.CharField(_("message au porteur (facultatif)"), max_length=200, blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("project", "user")]
        verbose_name = _("intention d'investissement")
        verbose_name_plural = _("intentions d'investissement")


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "project")]


class FinancialReport(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", _("Soumis")
        VERIFIED = "verified", _("Vérifié")
        FLAGGED = "flagged", _("À clarifier")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="reports")
    period_start = models.DateField(_("début de la période"))
    period_end = models.DateField(_("fin de la période"))
    due_date = models.DateField(_("à remettre avant le"))
    revenue = models.DecimalField(_("ventes / chiffre d'affaires"), **MONEY)
    cogs = models.DecimalField(_("coût des marchandises vendues"), **MONEY, default=ZERO)
    expenses = models.DecimalField(_("charges d'exploitation"), **MONEY, default=ZERO)
    net_profit = models.DecimalField(_("bénéfice net"), **MONEY, editable=False, default=ZERO)
    inventory_value = models.DecimalField(_("valeur du stock en fin de période"), **MONEY, default=ZERO)
    cash_balance = models.DecimalField(_("trésorerie en fin de période"), **MONEY, default=ZERO)
    customer_credit = models.DecimalField(_("crédit clients en fin de période"), **MONEY, default=ZERO)
    notes = models.TextField(_("commentaires"), blank=True)
    attachment = models.FileField(_("justificatif (photo du cahier, relevé…)"), upload_to="projects/reports/",
                                  storage=private_storage, validators=[validate_document], blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    staff_comment = models.TextField(_("commentaire de l'équipe"), blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")

    class Meta:
        ordering = ["-period_start"]
        unique_together = [("project", "period_start")]
        verbose_name = _("rapport financier")
        verbose_name_plural = _("rapports financiers")

    def __str__(self):
        return f"{self.project} {self.period_start:%Y-%m}"

    def save(self, *args, **kwargs):
        self.net_profit = self.revenue - self.cogs - self.expenses
        super().save(*args, **kwargs)

    @property
    def on_time(self):
        return self.submitted_at.date() <= self.due_date if self.submitted_at else False

    @property
    def investors_share(self):
        if not self.project.is_moucharaka or self.net_profit <= 0:
            return ZERO
        return (self.net_profit * (self.project.investor_profit_share_pct or ZERO) / 100).quantize(Decimal("0.01"))

    @property
    def distribution(self):
        return self.distributions.filter(status="paid").first()


class Installment(models.Model):
    """Mourabaha repayment schedule (generated when funds are released)."""

    class Status(models.TextChoices):
        UPCOMING = "upcoming", _("À venir")
        PAID = "paid", _("Payée")
        LATE = "late", _("En retard")
        DEFAULTED = "defaulted", _("Impayée")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="installments")
    number = models.PositiveSmallIntegerField()
    due_date = models.DateField()
    principal = models.DecimalField(**MONEY)
    margin = models.DecimalField(**MONEY)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UPCOMING)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["number"]
        unique_together = [("project", "number")]

    @property
    def amount(self):
        return self.principal + self.margin

    @property
    def days_late(self):
        ref = self.paid_at.date() if self.paid_at else date.today()
        return max((ref - self.due_date).days, 0)
