from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

MONEY = dict(max_digits=14, decimal_places=2)


class Listing(models.Model):
    """Fixed-price offer to sell parts of a project. Buyers may take all or
    part of the remaining quantity."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("En vente")
        SOLD = "sold", _("Vendu")
        CANCELLED = "cancelled", _("Retiré")
        EXPIRED = "expired", _("Expiré")

    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="listings")
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="listings")
    shares = models.PositiveIntegerField(_("parts mises en vente"))
    remaining = models.PositiveIntegerField()
    price_per_share = models.DecimalField(_("prix par part (MRU)"), **MONEY)
    allow_partial = models.BooleanField(_("vente partielle acceptée"), default=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    note = models.CharField(_("message aux acheteurs"), max_length=200, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price_per_share", "created_at"]
        verbose_name = _("annonce de vente")
        verbose_name_plural = _("annonces de vente")

    def __str__(self):
        return f"{self.remaining}/{self.shares} × {self.project} @ {self.price_per_share}"

    @property
    def premium_pct(self):
        nominal = self.project.share_price
        return ((self.price_per_share - nominal) * 100 / nominal).quantize(Decimal("0.1")) if nominal else None


class Trade(models.Model):
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="trades")
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="trades")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="buys")
    seller = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sells")
    shares = models.PositiveIntegerField()
    price_per_share = models.DecimalField(**MONEY)
    gross = models.DecimalField(**MONEY)
    buyer_fee = models.DecimalField(**MONEY)
    seller_fee = models.DecimalField(**MONEY)
    reference = models.CharField(max_length=24)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("transaction de marché")
        verbose_name_plural = _("transactions de marché")
