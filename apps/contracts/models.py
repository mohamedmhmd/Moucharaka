"""Signed contracts.

Every commitment of money (investing, receiving funds, selling or buying parts,
buybacks, the final repayment) goes through a contract the person reads and
signs with a one-time code sent to their verified WhatsApp number. The text
they read is frozen with a fingerprint (SHA-256), together with who signed,
when, from which connection and with which code request.
"""
import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


def new_contract_reference():
    return "CT-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _i in range(8))


class Contract(models.Model):
    class Kind(models.TextChoices):
        DEAL_INVESTMENT = "deal_investment", _("Contrat de participation (opération ponctuelle)")
        SHARE_PURCHASE = "share_purchase", _("Contrat de souscription de parts")
        FUNDING = "funding", _("Contrat de financement (porteur)")
        SHARE_ISSUE = "share_issue", _("Engagement d'émission de parts (entreprise)")
        SALE_OFFER = "sale_offer", _("Offre de vente de parts (marché)")
        SHARE_TRANSFER = "share_transfer", _("Contrat de cession de parts")
        BUYBACK_OFFER = "buyback_offer", _("Offre de rachat de parts")
        BUYBACK = "buyback", _("Contrat de rachat de parts")
        SETTLEMENT = "settlement", _("Acte de remboursement final")

    class Status(models.TextChoices):
        PENDING = "pending", _("En attente de signature")
        SIGNED = "signed", _("Signé")
        CANCELLED = "cancelled", _("Non signé")
        TERMINATED = "terminated", _("Résilié")

    reference = models.CharField(max_length=12, unique=True, default=new_contract_reference, editable=False)
    kind = models.CharField(_("type"), max_length=16, choices=Kind.choices)
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.PENDING,
                              db_index=True)
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="contracts",
                                null=True, blank=True)
    title = models.CharField(_("titre"), max_length=200)
    language = models.CharField(max_length=5, default="ar")
    body = models.TextField(_("texte du contrat"))
    body_hash = models.CharField(_("empreinte du texte (SHA-256)"), max_length=64)
    seal_hash = models.CharField(_("empreinte du contrat signé (SHA-256)"), max_length=64, blank=True)
    terms = models.JSONField(_("conditions"), default=dict, blank=True)
    # What happens when it is signed (see apps/contracts/actions.py)
    action = models.CharField(max_length=40)
    payload = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="contracts_created")
    viewers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="contracts", blank=True,
                                     help_text=_("Parties qui peuvent lire le contrat dans leur espace."))
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children",
                               help_text=_("Offre signée par l'autre partie sur laquelle ce contrat s'appuie."))
    object_ref = models.CharField(_("opération liée"), max_length=60, blank=True,
                                  help_text=_("Référence de l'investissement, de l'annonce, de l'échange…"))
    error = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    terminated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("contrat")
        verbose_name_plural = _("contrats")

    def __str__(self):
        return f"{self.reference} · {self.title}"

    def get_absolute_url(self):
        return reverse("contracts:detail", args=[self.reference])

    @staticmethod
    def fingerprint(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def compute_seal(self):
        parts = [self.reference, self.body_hash]
        for s in self.signatures.order_by("signed_at", "id"):
            parts.append(f"{s.role}|{s.full_name}|{s.nni}|{s.phone}|{s.signed_at.isoformat()}|{s.ip}|{s.otp_id}")
        return self.fingerprint("\n".join(parts))

    def visible_to(self, user):
        return user.is_staff or self.viewers.filter(pk=user.pk).exists()


class Signature(models.Model):
    class Role(models.TextChoices):
        INVESTOR = "investor", _("Investisseur")
        OWNER = "owner", _("Porteur de projet")
        COMPANY = "company", _("Entreprise, représentée par son porteur")
        SELLER = "seller", _("Vendeur")
        BUYER = "buyer", _("Acheteur")
        SHAREHOLDER = "shareholder", _("Actionnaire")

    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="signatures")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="signatures")
    role = models.CharField(max_length=12, choices=Role.choices)
    full_name = models.CharField(max_length=150)
    nni = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=16)
    signed_at = models.DateTimeField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    method = models.CharField(max_length=30, default="whatsapp_otp")
    otp_id = models.PositiveIntegerField(null=True, blank=True)
    from_contract = models.ForeignKey(Contract, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                      help_text=_("Signature donnée sur l'offre de l'autre partie."))

    class Meta:
        ordering = ["signed_at"]
        verbose_name = _("signature")

    def __str__(self):
        return f"{self.full_name} ({self.get_role_display()})"
