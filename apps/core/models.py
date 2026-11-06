from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import models
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


class TimeStamped(models.Model):
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        abstract = True


class Bilingual(models.Model):
    """Admin-editable reference data carries both languages."""

    name_fr = models.CharField(_("nom (français)"), max_length=160)
    name_ar = models.CharField(_("nom (arabe)"), max_length=160)

    class Meta:
        abstract = True

    @property
    def name(self):
        return self.name_ar if (get_language() or "").startswith("ar") else self.name_fr

    def __str__(self):
        return self.name


class Wilaya(Bilingual):
    code = models.CharField(max_length=8, unique=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name_fr"]
        verbose_name = _("wilaya")
        verbose_name_plural = _("wilayas")


class Moughataa(Bilingual):
    wilaya = models.ForeignKey(Wilaya, on_delete=models.CASCADE, related_name="moughataas")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    class Meta:
        ordering = ["wilaya__order", "name_fr"]
        verbose_name = _("moughataa")
        verbose_name_plural = _("moughataas")


class PlatformSettings(models.Model):
    """Singleton holding every commercial parameter of the platform.

    Per-project-type fees live in FeePolicy; market and wallet fees here.
    """

    # Secondary market
    trade_fee_buyer_pct = models.DecimalField(_("frais acheteur marché (%)"), max_digits=5, decimal_places=2, default=Decimal("1.00"))
    trade_fee_seller_pct = models.DecimalField(_("frais vendeur marché (%)"), max_digits=5, decimal_places=2, default=Decimal("1.00"))
    max_listing_premium_pct = models.DecimalField(
        _("prix max. d'une annonce (% au-dessus de la valeur nominale)"), max_digits=6, decimal_places=2, default=Decimal("50.00"),
        help_text=_("Garde-fou contre la spéculation excessive."))
    # Wallet
    withdrawal_fee_flat = models.DecimalField(_("frais fixes de retrait (MRU)"), max_digits=10, decimal_places=2, default=Decimal("20.00"))
    withdrawal_fee_pct = models.DecimalField(_("frais de retrait (%)"), max_digits=5, decimal_places=2, default=Decimal("0.50"))
    min_withdrawal = models.DecimalField(_("retrait minimum (MRU)"), max_digits=12, decimal_places=2, default=Decimal("200.00"))
    min_deposit = models.DecimalField(_("dépôt minimum (MRU)"), max_digits=12, decimal_places=2, default=Decimal("100.00"))
    # Investor protection
    max_ticket_pct = models.DecimalField(
        _("part max. d'un investisseur dans une campagne (%)"), max_digits=5, decimal_places=2, default=Decimal("40.00"))
    # Owner discipline
    report_grace_days = models.PositiveSmallIntegerField(_("délai de remise des rapports (jours après la période)"), default=10)
    installment_grace_days = models.PositiveSmallIntegerField(_("délai de grâce des échéances (jours)"), default=5)
    max_campaign_days = models.PositiveSmallIntegerField(_("durée max. d'une campagne (jours)"), default=60)
    featured_fee = models.DecimalField(_("mise en avant d'un projet (MRU / 7 jours)"), max_digits=10, decimal_places=2, default=Decimal("100.00"))
    # Payment instructions shown to users for manual mobile-money deposits
    merchant_bankily = models.CharField(_("numéro marchand Bankily"), max_length=40, blank=True)
    merchant_masrvi = models.CharField(_("numéro marchand Masrvi"), max_length=40, blank=True)
    merchant_sedad = models.CharField(_("numéro marchand Sedad"), max_length=40, blank=True)
    bank_details = models.TextField(_("coordonnées bancaires pour virements"), blank=True)
    support_phone = models.CharField(_("téléphone support"), max_length=40, blank=True)
    # Identity of the operator, printed in every contract
    legal_name = models.CharField(_("raison sociale de l'exploitant"), max_length=200, blank=True,
                                  help_text=_("Société ou personne qui exploite la plateforme, telle qu'enregistrée."))
    legal_registration = models.CharField(_("immatriculation (RC / NIF)"), max_length=120, blank=True)
    legal_address = models.CharField(_("adresse du siège"), max_length=255, blank=True)
    legal_city = models.CharField(_("ville des contrats et des litiges"), max_length=80, default="Nouakchott")
    contact_email = models.EmailField(_("e-mail de contact"), blank=True, default="moucharaka.mr@gmail.com",
                                      help_text=_("Affiché sur la page Contact et en bas de chaque page."))

    class Meta:
        verbose_name = _("paramètres de la plateforme")
        verbose_name_plural = _("paramètres de la plateforme")

    def __str__(self):
        return str(_("Paramètres de la plateforme"))

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete("platform_settings")

    @classmethod
    def get(cls):
        obj = cache.get("platform_settings")
        if obj is None:
            obj, _created = cls.objects.get_or_create(pk=1)
            cache.set("platform_settings", obj, 300)
        return obj


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("notification")

    def __str__(self):
        return self.title


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=80, db_index=True)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=40, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    target_repr = models.CharField(max_length=200, blank=True)
    data = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("journal d'audit")
        verbose_name_plural = _("journal d'audit")

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target_repr}"
