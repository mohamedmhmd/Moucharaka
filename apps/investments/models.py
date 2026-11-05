from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

ZERO = Decimal("0")
MONEY = dict(max_digits=14, decimal_places=2)


class Investment(models.Model):
    """A subscription during the campaign. Money is held in escrow until the
    campaign succeeds (settled → shares) or fails (refunded)."""

    class Status(models.TextChoices):
        HELD = "held", _("Fonds bloqués (collecte en cours)")
        SETTLED = "settled", _("Confirmé")
        REFUNDED = "refunded", _("Remboursé")
        CANCELLED = "cancelled", _("Annulé par l'investisseur")

    investor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="investments")
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="investments")
    shares = models.PositiveIntegerField(_("parts"))
    amount = models.DecimalField(_("montant"), **MONEY)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.HELD, db_index=True)
    reference = models.CharField(max_length=24)
    risk_acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("souscription")
        verbose_name_plural = _("souscriptions")

    def __str__(self):
        return f"{self.investor} → {self.project} ({self.shares})"


class Holding(models.Model):
    """Current ownership of parts in a project (changes with trades/buybacks)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="holdings")
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="holdings")
    shares = models.PositiveIntegerField(default=0)
    locked_shares = models.PositiveIntegerField(default=0, help_text=_("Parts mises en vente sur le marché."))
    cost_basis = models.DecimalField(_("prix de revient total"), **MONEY, default=ZERO)
    received_total = models.DecimalField(_("distributions reçues"), **MONEY, default=ZERO)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "project")]
        verbose_name = _("détention de parts")
        verbose_name_plural = _("détentions de parts")
        constraints = [models.CheckConstraint(condition=models.Q(locked_shares__lte=models.F("shares")),
                                              name="holding_locked_lte_shares")]

    def __str__(self):
        return f"{self.user} {self.shares} × {self.project}"

    @property
    def free_shares(self):
        return self.shares - self.locked_shares

    @property
    def nominal_value(self):
        return self.shares * self.project.share_price

    @property
    def market_value(self):
        price = self.project.last_trade_price or self.project.share_price
        return self.shares * price

    @property
    def avg_cost(self):
        return (self.cost_basis / self.shares).quantize(Decimal("0.01")) if self.shares else ZERO


class Distribution(models.Model):
    """Money paid by the project owner to all holders, pro rata to shares."""

    class Kind(models.TextChoices):
        PROFIT = "profit", _("Partage des bénéfices (Moucharaka)")
        INSTALLMENT = "installment", _("Échéance (Mourabaha)")
        BUYBACK = "buyback", _("Rachat de parts")
        LIQUIDATION = "liquidation", _("Produit de liquidation")
        SETTLEMENT = "settlement", _("Remboursement final (capital et bénéfice)")

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="distributions")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    report = models.ForeignKey("projects.FinancialReport", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="distributions")
    installment = models.ForeignKey("projects.Installment", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="distributions")
    gross_amount = models.DecimalField(_("montant versé par le porteur"), **MONEY)
    fee_base = models.DecimalField(_("assiette de la commission"), **MONEY, default=ZERO)
    platform_fee = models.DecimalField(_("commission plateforme"), **MONEY, default=ZERO)
    net_amount = models.DecimalField(_("net distribué"), **MONEY, default=ZERO)
    shares_outstanding = models.PositiveIntegerField(default=0)
    per_share = models.DecimalField(max_digits=14, decimal_places=4, default=ZERO)
    shares_retired = models.PositiveIntegerField(default=0, help_text=_("Parts rachetées et annulées (rachat)."))
    status = models.CharField(max_length=10, default="paid")
    due_date = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(auto_now_add=True)
    on_time = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=24)

    class Meta:
        ordering = ["-paid_at"]
        verbose_name = _("distribution")
        verbose_name_plural = _("distributions")

    def __str__(self):
        return f"{self.project} {self.get_kind_display()} {self.net_amount}"


class Payout(models.Model):
    distribution = models.ForeignKey(Distribution, on_delete=models.CASCADE, related_name="payouts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payouts")
    shares = models.PositiveIntegerField()
    amount = models.DecimalField(**MONEY)

    class Meta:
        ordering = ["-distribution__paid_at"]


class DealSettlement(models.Model):
    """One-off operation: the owner sends back one total (capital + profit).
    The money waits on the owner's wallet until the team validates it, then it
    is shared between the investors in proportion to what each put in."""

    class Status(models.TextChoices):
        PENDING = "pending", _("En attente de validation")
        VALIDATED = "validated", _("Validé et versé")
        REJECTED = "rejected", _("Refusé")
        CANCELLED = "cancelled", _("Annulé par le porteur")

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="settlements")
    amount = models.DecimalField(_("montant rendu aux investisseurs"), **MONEY)
    capital = models.DecimalField(_("capital des investisseurs"), **MONEY, default=ZERO)
    note = models.TextField(_("message du porteur"), blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    staff_reason = models.CharField(_("motif"), max_length=255, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    distribution = models.OneToOneField(Distribution, null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name="settlement")
    reference = models.CharField(max_length=24)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("remboursement final")
        verbose_name_plural = _("remboursements finaux")

    def __str__(self):
        return f"{self.project} {self.amount} ({self.status})"

    @property
    def gain(self):
        return self.amount - self.capital
