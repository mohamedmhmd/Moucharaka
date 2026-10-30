from django.db import models
from django.utils.translation import gettext_lazy as _


class SMSProvider(models.Model):
    """A messaging gateway (WhatsApp or SMS) configured from the admin.

    Several providers can be active at once. For each channel (WhatsApp first,
    then SMS if enabled) messages go to the provider with the lowest priority
    number and fail over to the next one.
    """

    CHANNELS = [("whatsapp", "WhatsApp"), ("sms", "SMS")]
    BACKENDS = [
        ("whatsapp_cloud", _("WhatsApp — API Cloud de Meta (direct)")),
        ("twilio_whatsapp", _("WhatsApp — Twilio")),
        ("console", _("Console (développement, n'envoie rien)")),
        ("http", _("Passerelle HTTP générique (opérateur local / agrégateur)")),
        ("twilio", "SMS — Twilio"),
        ("infobip", "SMS — Infobip"),
        ("vonage", "SMS — Vonage (Nexmo)"),
    ]

    name = models.CharField(_("nom"), max_length=80)
    channel = models.CharField(_("canal"), max_length=10, choices=CHANNELS, default="whatsapp")
    backend = models.CharField(_("type"), max_length=20, choices=BACKENDS, default="whatsapp_cloud")
    is_active = models.BooleanField(_("actif"), default=True)
    priority = models.PositiveSmallIntegerField(_("priorité"), default=10, help_text=_("Le plus petit numéro est essayé en premier."))
    sender_id = models.CharField(_("expéditeur (Sender ID)"), max_length=20, blank=True)
    prefixes = models.CharField(
        _("préfixes desservis"), max_length=120, blank=True,
        help_text=_("Optionnel. Indicatifs internationaux servis par ce fournisseur, sans « + ». Ex : 222 (Mauritanie), "
                    "2223 (Mattel), 33,34 (France, Espagne). Vide = tous les pays."))
    config = models.JSONField(
        _("configuration"), default=dict, blank=True,
        help_text=_("Paramètres propres au fournisseur (voir docs/SMS.md). Ex. HTTP : url, method, params, headers, body_format, success_contains."))
    sent_count = models.PositiveIntegerField(default=0, editable=False)
    failed_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["priority", "id"]
        verbose_name = _("fournisseur de messagerie")
        verbose_name_plural = _("fournisseurs de messagerie (WhatsApp, SMS)")

    def __str__(self):
        return f"{self.name} ({self.get_backend_display()})"

    def save(self, *args, **kwargs):
        from .backends import WHATSAPP_BACKENDS

        if self.backend in WHATSAPP_BACKENDS:
            self.channel = "whatsapp"
        elif self.backend in ("twilio", "infobip", "vonage"):
            self.channel = "sms"
        super().save(*args, **kwargs)

    def serves(self, e164: str) -> bool:
        if not self.prefixes.strip():
            return True
        digits = e164.lstrip("+")
        prefixes = [p.strip().lstrip("+") for p in self.prefixes.split(",") if p.strip()]
        return any(digits.startswith(p) for p in prefixes)


class SMSMessage(models.Model):
    STATUS = [("sent", _("envoyé")), ("failed", _("échec"))]
    phone = models.CharField(max_length=20, db_index=True)
    channel = models.CharField(max_length=10, default="whatsapp")
    body = models.TextField()
    purpose = models.CharField(max_length=30, blank=True)
    provider = models.ForeignKey(SMSProvider, null=True, blank=True, on_delete=models.SET_NULL)
    backend = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=STATUS)
    provider_message_id = models.CharField(max_length=120, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("message envoyé")
        verbose_name_plural = _("journal des messages")

    def __str__(self):
        return f"{self.phone} {self.status}"
