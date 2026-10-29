from django.db import models
from django.utils.translation import gettext_lazy as _


class SMSProvider(models.Model):
    """An SMS gateway configured from the admin.

    Several providers can be active at once: messages go to the provider with
    the lowest priority number first and fail over to the next one.
    """

    BACKENDS = [
        ("console", _("Console (développement, n'envoie rien)")),
        ("http", _("Passerelle HTTP générique (opérateur local / agrégateur)")),
        ("twilio", "Twilio"),
        ("infobip", "Infobip"),
        ("vonage", "Vonage (Nexmo)"),
    ]

    name = models.CharField(_("nom"), max_length=80)
    backend = models.CharField(_("type"), max_length=20, choices=BACKENDS, default="http")
    is_active = models.BooleanField(_("actif"), default=True)
    priority = models.PositiveSmallIntegerField(_("priorité"), default=10, help_text=_("Le plus petit numéro est essayé en premier."))
    sender_id = models.CharField(_("expéditeur (Sender ID)"), max_length=20, blank=True)
    prefixes = models.CharField(
        _("préfixes desservis"), max_length=120, blank=True,
        help_text=_("Optionnel. Ex : 2,3,4 pour ne router que les numéros commençant par ces chiffres (Chinguitel, Mattel, Mauritel). Vide = tous."))
    config = models.JSONField(
        _("configuration"), default=dict, blank=True,
        help_text=_("Paramètres propres au fournisseur (voir docs/SMS.md). Ex. HTTP : url, method, params, headers, body_format, success_contains."))
    sent_count = models.PositiveIntegerField(default=0, editable=False)
    failed_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["priority", "id"]
        verbose_name = _("fournisseur SMS")
        verbose_name_plural = _("fournisseurs SMS")

    def __str__(self):
        return f"{self.name} ({self.get_backend_display()})"

    def serves(self, local_number: str) -> bool:
        if not self.prefixes.strip():
            return True
        prefixes = [p.strip() for p in self.prefixes.split(",") if p.strip()]
        return any(local_number.startswith(p) for p in prefixes)


class SMSMessage(models.Model):
    STATUS = [("sent", _("envoyé")), ("failed", _("échec"))]
    phone = models.CharField(max_length=20, db_index=True)
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
        verbose_name = _("SMS envoyé")
        verbose_name_plural = _("journal SMS")

    def __str__(self):
        return f"{self.phone} {self.status}"
