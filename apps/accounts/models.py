import hashlib
import hmac
import secrets
import uuid
from datetime import date

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from .phones import display_phone, normalize_phone, validate_phone  # noqa: F401

phone_validator = validate_phone  # kept for existing imports
nni_validator = RegexValidator(r"^\d{10}$", _("Le NNI comporte 10 chiffres."))


class PrivateStorage(FileSystemStorage):
    """Storage outside MEDIA_ROOT; files are only reachable through a view
    that checks permissions."""

    def __init__(self):
        super().__init__(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)

    def deconstruct(self):
        return ("apps.accounts.models.PrivateStorage", (), {})


private_storage = PrivateStorage()


def kyc_upload_to(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower()[:5] if "." in filename else "bin"
    return f"kyc/{instance.user_id}/{uuid.uuid4().hex}.{ext}"


def validate_document(f):
    allowed = {"jpg", "jpeg", "png", "webp", "pdf", "heic"}
    ext = f.name.rsplit(".", 1)[-1].lower() if "." in f.name else ""
    if ext not in allowed:
        raise ValidationError(_("Format accepté : JPG, PNG, WEBP, HEIC ou PDF."))
    if f.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise ValidationError(_("Fichier trop volumineux (max. %(mb)s Mo).") % {"mb": settings.MAX_UPLOAD_MB})


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, phone, password=None, **extra):
        phone = normalize_phone(phone)
        if not phone:
            raise ValueError("phone is required")
        user = self.model(phone=phone, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, status=User.Status.APPROVED)
        extra.setdefault("full_name", "Admin")
        return self.create_user(phone, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    class Status(models.TextChoices):
        NEW = "new", _("Identité à compléter")
        PENDING = "pending", _("En cours de vérification")
        APPROVED = "approved", _("Vérifié")
        REJECTED = "rejected", _("Refusé")
        SUSPENDED = "suspended", _("Suspendu")

    phone = models.CharField(_("numéro WhatsApp"), max_length=16, unique=True, validators=[validate_phone],
                             help_text=_("Format international E.164, ex. +22222123456"))
    whatsapp_notifications = models.BooleanField(
        _("recevoir les notifications importantes sur WhatsApp"), default=True,
        help_text=_("Versements, échéances, validation du compte. Les codes de connexion sont toujours envoyés."))
    full_name = models.CharField(_("nom complet"), max_length=150)
    email = models.EmailField(_("e-mail"), blank=True)
    preferred_language = models.CharField(_("langue"), max_length=5, choices=settings.LANGUAGES, default="ar")
    status = models.CharField(_("statut"), max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    public_id = models.CharField(max_length=12, unique=True, editable=False)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    is_staff = models.BooleanField(_("équipe"), default=False)
    is_active = models.BooleanField(_("actif"), default=True)
    date_joined = models.DateTimeField(_("inscrit le"), default=timezone.now)

    objects = UserManager()
    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")

    def __str__(self):
        return f"{self.full_name} ({self.phone})"

    def save(self, *args, **kwargs):
        if not self.public_id:
            self.public_id = secrets.token_hex(5)
        # Always store E.164 (+22236123456), whatever was typed in a form or the admin,
        # so login (which normalizes what the user types) finds the account.
        if self.phone:
            self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    @property
    def is_approved(self):
        return self.status == self.Status.APPROVED and self.is_active

    @property
    def masked_phone(self):
        return f"{self.phone[:6]}••••{self.phone[-2:]}"

    @property
    def phone_display(self):
        return display_phone(self.phone)

    @property
    def display_name(self):
        """Public name: first name + initial of the rest (privacy)."""
        parts = self.full_name.split()
        if len(parts) <= 1:
            return self.full_name
        return f"{parts[0]} {parts[-1][0]}."

    @cached_property
    def wallet(self):
        from apps.wallet.models import Wallet

        return Wallet.for_user(self)


class KYCProfile(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        SUBMITTED = "submitted", _("Soumis")
        APPROVED = "approved", _("Approuvé")
        REJECTED = "rejected", _("Refusé")
        RESUBMIT = "resubmit", _("Corrections demandées")

    ID_TYPES = [("cni", _("Carte nationale d'identité")), ("passport", _("Passeport")),
                ("residence", _("Carte de séjour"))]
    GENDERS = [("m", _("Homme")), ("f", _("Femme"))]
    INCOME = [("lt20k", _("Moins de 20 000 MRU / mois")), ("20-50k", _("20 000 – 50 000 MRU")),
              ("50-150k", _("50 000 – 150 000 MRU")), ("gt150k", _("Plus de 150 000 MRU"))]
    FUNDS = [("salary", _("Salaire")), ("business", _("Activité commerciale")), ("savings", _("Épargne")),
             ("family", _("Famille / transferts")), ("livestock", _("Élevage / agriculture")),
             ("pension", _("Pension")), ("other", _("Autre"))]
    EXPERIENCE = [("none", _("Aucune")), ("informal", _("Associations / caisses d'entraide informelles")),
                  ("some", _("J'ai déjà investi dans des commerces")), ("pro", _("Investisseur expérimenté"))]
    PURPOSE = [("invest", _("Investir")), ("raise", _("Financer mon projet")), ("both", _("Les deux"))]
    RISK = [("low", _("Faible")), ("medium", _("Moyen")), ("high", _("Élevé"))]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="kyc")
    # Identity
    full_name = models.CharField(_("nom complet"), max_length=150,
                                 help_text=_("En lettres latines ou en arabe, comme sur votre pièce d'identité."))
    nni = models.CharField(_("NNI"), max_length=10, unique=True, validators=[nni_validator],
                           help_text=_("Numéro national d'identification, 10 chiffres."))
    id_type = models.CharField(_("pièce d'identité"), max_length=12, choices=ID_TYPES, default="cni")
    id_number = models.CharField(_("numéro de la pièce"), max_length=30)
    id_issue_date = models.DateField(_("date de délivrance"))
    id_expiry_date = models.DateField(_("date d'expiration"))
    date_of_birth = models.DateField(_("date de naissance"))
    place_of_birth = models.CharField(_("lieu de naissance"), max_length=100)
    gender = models.CharField(_("sexe"), max_length=1, choices=GENDERS)
    nationality = models.CharField(_("nationalité"), max_length=60, default="Mauritanienne")
    # Address
    wilaya = models.ForeignKey("core.Wilaya", on_delete=models.PROTECT, verbose_name=_("wilaya"))
    moughataa = models.ForeignKey("core.Moughataa", on_delete=models.PROTECT, verbose_name=_("moughataa"))
    address = models.CharField(_("quartier / adresse"), max_length=200)
    # Financial profile (AML / suitability)
    profession = models.CharField(_("profession"), max_length=100)
    employer = models.CharField(_("employeur / activité"), max_length=120, blank=True)
    monthly_income = models.CharField(_("revenu mensuel"), max_length=10, choices=INCOME)
    source_of_funds = models.CharField(_("origine des fonds"), max_length=12, choices=FUNDS)
    experience = models.CharField(_("expérience d'investissement"), max_length=10, choices=EXPERIENCE)
    purpose = models.CharField(_("vous venez pour"), max_length=8, choices=PURPOSE, default="both")
    is_pep = models.BooleanField(_("je suis (ou un proche est) une personnalité politiquement exposée"), default=False)
    # Documents (private storage)
    id_front = models.FileField(_("pièce d'identité — recto"), upload_to=kyc_upload_to, storage=private_storage,
                                validators=[validate_document])
    id_back = models.FileField(_("pièce d'identité — verso"), upload_to=kyc_upload_to, storage=private_storage,
                               validators=[validate_document], blank=True)
    # Review
    status = models.CharField(_("statut"), max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    risk_level = models.CharField(_("niveau de risque"), max_length=8, choices=RISK, blank=True)
    rejection_reason = models.TextField(_("motif du refus / corrections"), blank=True)
    review_notes = models.TextField(_("notes internes"), blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    terms_accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("dossier KYC")
        verbose_name_plural = _("dossiers KYC")

    def __str__(self):
        return f"KYC {self.full_name} ({self.nni})"

    @property
    def age(self):
        today = date.today()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def clean(self):
        errors = {}
        if self.date_of_birth and self.age < 18:
            errors["date_of_birth"] = _("Vous devez avoir au moins 18 ans.")
        if self.id_expiry_date and self.id_expiry_date < date.today():
            errors["id_expiry_date"] = _("La pièce d'identité est expirée.")
        if self.id_issue_date and self.id_expiry_date and self.id_issue_date >= self.id_expiry_date:
            errors["id_expiry_date"] = _("La date d'expiration doit suivre la date de délivrance.")
        if self.moughataa_id and self.wilaya_id and self.moughataa.wilaya_id != self.wilaya_id:
            errors["moughataa"] = _("Cette moughataa n'appartient pas à la wilaya choisie.")
        if errors:
            raise ValidationError(errors)

    def automated_checks(self):
        """Cheap consistency checks shown to reviewers (not a decision)."""
        flags = []
        if self.is_pep:
            flags.append(_("Personne politiquement exposée : vigilance renforcée."))
        if self.id_type == "cni" and self.id_number and self.nni and self.nni not in self.id_number and self.id_number not in self.nni:
            flags.append(_("Le numéro de la CNI ne contient pas le NNI : vérifier."))
        if self.id_expiry_date and (self.id_expiry_date - date.today()).days < 90:
            flags.append(_("La pièce expire dans moins de 3 mois."))
        if KYCProfile.objects.filter(full_name__iexact=self.full_name, date_of_birth=self.date_of_birth).exclude(pk=self.pk).exists():
            flags.append(_("Un autre dossier porte le même nom et la même date de naissance."))
        if self.user.full_name and self.user.full_name.split()[0].lower() not in self.full_name.lower():
            flags.append(_("Le nom du compte diffère du nom sur la pièce."))
        return flags


class PhoneOTP(models.Model):
    class Purpose(models.TextChoices):
        REGISTER = "register", _("Inscription")
        LOGIN = "login", _("Connexion")
        RESET = "reset", _("Mot de passe oublié")
        WITHDRAW = "withdraw", _("Retrait")

    phone = models.CharField(max_length=16, db_index=True)
    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("code OTP")

    @staticmethod
    def hash_code(phone, purpose, code):
        key = settings.SECRET_KEY.encode()
        return hmac.new(key, f"{phone}:{purpose}:{code}".encode(), hashlib.sha256).hexdigest()

    @property
    def is_valid(self):
        return (self.consumed_at is None and self.expires_at > timezone.now()
                and self.attempts < settings.OTP_MAX_ATTEMPTS)
