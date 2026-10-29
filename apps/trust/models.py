from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class TrustEvent(models.Model):
    """A behaviour that moves a user's trust score. Points are fixed per kind
    in apps.trust.services.EVENT_POINTS unless staff set a manual value."""

    KINDS = [
        ("kyc_verified", _("Identité vérifiée")),
        ("campaign_funded", _("Collecte réussie")),
        ("campaign_failed", _("Collecte échouée")),
        ("report_on_time", _("Rapport remis à temps")),
        ("report_late", _("Rapport remis en retard")),
        ("report_missed", _("Rapport non remis")),
        ("report_flagged", _("Rapport contesté par l'équipe")),
        ("payment_on_time", _("Paiement à l'échéance")),
        ("payment_late", _("Paiement en retard")),
        ("installment_overdue", _("Échéance impayée")),
        ("default", _("Défaut de paiement")),
        ("project_completed", _("Projet mené à terme")),
        ("buyback", _("Rachat de parts effectué")),
        ("update_posted", _("Nouvelles données aux investisseurs")),
        ("manual", _("Ajustement de l'équipe")),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trust_events")
    kind = models.CharField(max_length=20, choices=KINDS, db_index=True)
    points = models.IntegerField()
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL)
    note = models.CharField(max_length=255, blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("événement de confiance")
        verbose_name_plural = _("événements de confiance")

    def __str__(self):
        return f"{self.user} {self.kind} {self.points:+d}"


class TrustScore(models.Model):
    GRADES = [("A+", "A+"), ("A", "A"), ("B", "B"), ("C", "C"), ("D", "D"), ("E", "E"), ("N", _("Nouveau"))]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trust")
    score = models.PositiveSmallIntegerField(default=0)
    grade = models.CharField(max_length=2, choices=GRADES, default="N")
    components = models.JSONField(default=dict)
    has_track_record = models.BooleanField(default=False)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("score de confiance")
        verbose_name_plural = _("scores de confiance")

    def __str__(self):
        return f"{self.user} {self.score} ({self.grade})"


class Review(models.Model):
    """Feedback from an investor about a project owner."""

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="reviews")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_given")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews_received")
    communication = models.PositiveSmallIntegerField(_("communication"), validators=[MinValueValidator(1), MaxValueValidator(5)])
    transparency = models.PositiveSmallIntegerField(_("transparence des comptes"), validators=[MinValueValidator(1), MaxValueValidator(5)])
    commitments = models.PositiveSmallIntegerField(_("respect des engagements"), validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(_("commentaire"), blank=True, max_length=1000)
    is_hidden = models.BooleanField(default=False, help_text=_("Masqué par la modération."))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = [("project", "reviewer")]
        verbose_name = _("avis d'investisseur")
        verbose_name_plural = _("avis d'investisseurs")

    @property
    def average(self):
        return round((self.communication + self.transparency + self.commitments) / 3, 1)
