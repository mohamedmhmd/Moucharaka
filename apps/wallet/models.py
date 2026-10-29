import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import private_storage, validate_document

ZERO = Decimal("0")
MONEY = dict(max_digits=14, decimal_places=2)


class Wallet(models.Model):
    """Internal account in MRU.

    `balance` is spendable money; `held` is money reserved (escrow for an open
    campaign, pending withdrawal). The platform's revenue sits in a single
    wallet with kind=platform.
    """

    KINDS = [("user", _("Utilisateur")), ("platform", _("Plateforme (revenus)"))]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="wallet_account")
    kind = models.CharField(max_length=10, choices=KINDS, default="user")
    balance = models.DecimalField(_("disponible"), **MONEY, default=ZERO)
    held = models.DecimalField(_("bloqué"), **MONEY, default=ZERO)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("portefeuille")
        verbose_name_plural = _("portefeuilles")
        constraints = [
            models.CheckConstraint(condition=models.Q(balance__gte=0), name="wallet_balance_non_negative"),
            models.CheckConstraint(condition=models.Q(held__gte=0), name="wallet_held_non_negative"),
        ]

    def __str__(self):
        return f"{self.user or 'PLATFORM'}: {self.balance} MRU"

    @property
    def total(self):
        return self.balance + self.held

    @classmethod
    def for_user(cls, user):
        wallet, _created = cls.objects.get_or_create(user=user, defaults={"kind": "user"})
        return wallet

    @classmethod
    def platform(cls):
        wallet = cls.objects.filter(kind="platform").first()
        if wallet is None:
            wallet = cls.objects.create(kind="platform")
        return wallet


class Transaction(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = "deposit", _("Dépôt")
        WITHDRAWAL = "withdrawal", _("Retrait")
        WITHDRAWAL_HOLD = "withdrawal_hold", _("Retrait en attente")
        WITHDRAWAL_RELEASE = "withdrawal_release", _("Retrait annulé")
        INVEST_HOLD = "invest_hold", _("Investissement (fonds bloqués)")
        INVEST_REFUND = "invest_refund", _("Remboursement de collecte")
        INVEST_SETTLE = "invest_settle", _("Investissement transféré au projet")
        FUNDING = "funding", _("Fonds reçus pour le projet")
        REVIEW_FEE = "review_fee", _("Frais d'étude")
        SUCCESS_FEE = "success_fee", _("Commission de succès")
        DISTRIBUTION_OUT = "distribution_out", _("Distribution versée aux investisseurs")
        DISTRIBUTION_IN = "distribution_in", _("Distribution reçue")
        MANAGEMENT_FEE = "management_fee", _("Commission de gestion")
        INSTALLMENT_OUT = "installment_out", _("Échéance Mourabaha payée")
        INSTALLMENT_IN = "installment_in", _("Échéance Mourabaha reçue")
        BUYBACK_OUT = "buyback_out", _("Rachat de parts payé")
        BUYBACK_IN = "buyback_in", _("Rachat de parts reçu")
        TRADE_BUY = "trade_buy", _("Achat de parts")
        TRADE_SELL = "trade_sell", _("Vente de parts")
        TRADE_FEE = "trade_fee", _("Frais de marché")
        WITHDRAWAL_FEE = "withdrawal_fee", _("Frais de retrait")
        FEATURED_FEE = "featured_fee", _("Mise en avant")
        ADJUSTMENT = "adjustment", _("Régularisation")

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)
    amount = models.DecimalField(_("montant"), **MONEY, help_text=_("Variation du solde disponible."))
    held_delta = models.DecimalField(**MONEY, default=ZERO)
    balance_after = models.DecimalField(**MONEY)
    held_after = models.DecimalField(**MONEY)
    reference = models.CharField(max_length=24, db_index=True)
    description = models.CharField(max_length=255, blank=True)
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="transactions")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("opération")
        verbose_name_plural = _("opérations")

    def __str__(self):
        return f"{self.reference} {self.kind} {self.amount}"


def new_reference(prefix="TX"):
    return f"{prefix}-{secrets.token_hex(4).upper()}"


class PaymentMethod(models.TextChoices):
    BANKILY = "bankily", "Bankily (BPM)"
    MASRVI = "masrvi", "Masrvi (BMCI)"
    SEDAD = "sedad", "Sedad"
    BANK = "bank", _("Virement bancaire")
    CASH = "cash", _("Espèces (agence partenaire)")


class DepositRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente du paiement")
        PROOF = "proof", _("Preuve envoyée, à vérifier")
        CONFIRMED = "confirmed", _("Confirmé")
        REJECTED = "rejected", _("Refusé")
        EXPIRED = "expired", _("Expiré")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="deposits")
    reference = models.CharField(max_length=16, unique=True, editable=False)
    amount = models.DecimalField(_("montant (MRU)"), **MONEY)
    method = models.CharField(_("moyen de paiement"), max_length=10, choices=PaymentMethod.choices)
    payer_phone = models.CharField(_("numéro payeur"), max_length=20, blank=True)
    external_ref = models.CharField(_("identifiant de la transaction"), max_length=80, blank=True,
                                    help_text=_("Numéro de transaction reçu par SMS de votre banque."))
    receipt = models.FileField(_("capture du reçu"), upload_to="deposits/", storage=private_storage,
                               validators=[validate_document], blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    gateway_payload = models.JSONField(default=dict, blank=True)
    staff_note = models.CharField(max_length=255, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("dépôt")
        verbose_name_plural = _("dépôts")
        constraints = [models.UniqueConstraint(fields=["method", "external_ref"], condition=~models.Q(external_ref=""),
                                               name="unique_external_ref_per_method")]

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = new_reference("DEP")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} {self.amount} MRU"


class WithdrawalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        PAID = "paid", _("Payé")
        REJECTED = "rejected", _("Refusé")
        CANCELLED = "cancelled", _("Annulé")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="withdrawals")
    reference = models.CharField(max_length=16, unique=True, editable=False)
    amount = models.DecimalField(_("montant (MRU)"), **MONEY)
    fee = models.DecimalField(_("frais"), **MONEY, default=ZERO)
    method = models.CharField(_("moyen de réception"), max_length=10, choices=PaymentMethod.choices)
    destination = models.CharField(_("numéro / RIB de réception"), max_length=60)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    external_ref = models.CharField(_("référence du paiement"), max_length=80, blank=True)
    staff_note = models.CharField(max_length=255, blank=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="+")
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("retrait")
        verbose_name_plural = _("retraits")

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = new_reference("WDR")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} {self.amount} MRU"

    @property
    def total(self):
        return self.amount + self.fee
