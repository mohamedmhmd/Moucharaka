from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.utils.translation import gettext_lazy as _

from apps.core.models import Moughataa
from apps.core.widgets import DateInput, MoughataaSelect

from .models import KYCProfile, User, normalize_phone, phone_validator


class PhoneField(forms.CharField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", _("Numéro WhatsApp"))
        kwargs.setdefault("max_length", 24)
        kwargs.setdefault("help_text", _("Le numéro qui utilise WhatsApp, dans n'importe quel pays. Mauritanie : 8 chiffres. "
                                         "Autres pays : + et l'indicatif, ex. +33 6 12 34 56 78."))
        kwargs.setdefault("widget", forms.TextInput(attrs={
            "type": "tel", "inputmode": "tel", "autocomplete": "tel", "placeholder": "22 12 34 56", "dir": "ltr"}))
        super().__init__(**kwargs)

    def clean(self, value):
        value = normalize_phone(super().clean(value))
        phone_validator(value)
        return value


class PhoneStartForm(forms.Form):
    phone = PhoneField()
    accept_terms = forms.BooleanField(label=_("J'accepte les conditions d'utilisation et la politique de confidentialité"))

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if User.objects.filter(phone=phone).exists():
            raise forms.ValidationError(_("Ce numéro a déjà un compte. Connectez-vous."))
        return phone


class OTPForm(forms.Form):
    code = forms.CharField(label=_("Code reçu sur WhatsApp"), max_length=8, widget=forms.TextInput(attrs={
        "inputmode": "numeric", "autocomplete": "one-time-code", "dir": "ltr", "class": "otp", "autofocus": True}))


class PasswordPairMixin(forms.Form):
    password1 = forms.CharField(label=_("Mot de passe"), widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label=_("Confirmez le mot de passe"), widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("Les deux mots de passe ne correspondent pas."))
        elif p1:
            try:
                password_validation.validate_password(p1)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return data


class RegisterFinishForm(PasswordPairMixin):
    full_name = forms.CharField(label=_("Nom complet"), max_length=150,
                                help_text=_("Tel qu'il apparaît sur votre pièce d'identité."))
    email = forms.EmailField(label=_("E-mail (facultatif)"), required=False)
    preferred_language = forms.ChoiceField(label=_("Langue des messages et notifications"), choices=settings.LANGUAGES)
    whatsapp_notifications = forms.BooleanField(
        label=_("J'accepte de recevoir sur WhatsApp les messages importants concernant mon compte "
                "(versements, échéances, validation)."), required=False, initial=True)
    field_order = ["full_name", "email", "preferred_language", "whatsapp_notifications", "password1", "password2"]


class LoginForm(forms.Form):
    phone = PhoneField()
    password = forms.CharField(label=_("Mot de passe"), widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class PhoneOnlyForm(forms.Form):
    phone = PhoneField()


class NewPasswordForm(PasswordPairMixin):
    pass


class SettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["email", "preferred_language", "whatsapp_notifications"]


class KYCForm(forms.ModelForm):
    confirm_truth = forms.BooleanField(
        label=_("Je certifie que ces informations sont exactes et j'autorise leur vérification."))

    class Meta:
        model = KYCProfile
        fields = [
            "full_name", "nni", "id_type", "id_number", "id_issue_date", "id_expiry_date",
            "date_of_birth", "place_of_birth", "gender", "nationality",
            "wilaya", "moughataa", "address",
            "profession", "employer", "monthly_income", "source_of_funds", "experience", "purpose", "is_pep",
            "id_front", "id_back",
        ]
        widgets = {
            "id_issue_date": DateInput(), "id_expiry_date": DateInput(), "date_of_birth": DateInput(),
            "moughataa": MoughataaSelect(attrs={"data-depends-on": "wilaya"}),
            "nni": forms.TextInput(attrs={"inputmode": "numeric", "dir": "ltr", "maxlength": 10}),
            "full_name": forms.TextInput(attrs={"dir": "auto"}),
            # No "capture" attribute: the phone offers the camera AND the gallery / files (photo or PDF).
            "id_front": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"}),
            "id_back": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"}),
        }

    fieldsets = [
        (_("Identité"), ["full_name", "nni", "id_type", "id_number", "id_issue_date",
                         "id_expiry_date", "date_of_birth", "place_of_birth", "gender", "nationality"]),
        (_("Adresse"), ["wilaya", "moughataa", "address"]),
        (_("Profil financier"), ["profession", "employer", "monthly_income", "source_of_funds", "experience",
                                 "purpose", "is_pep"]),
        (_("Documents"), ["id_front", "id_back"]),
        (_("Engagement"), ["confirm_truth"]),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["moughataa"].queryset = Moughataa.objects.select_related("wilaya")

    def clean_nni(self):
        nni = self.cleaned_data["nni"]
        qs = KYCProfile.objects.filter(nni=nni)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(_("Ce NNI est déjà associé à un autre compte. Contactez le support."))
        return nni

    def iter_fieldsets(self):
        for title, names in self.fieldsets:
            yield title, [self[n] for n in names]
