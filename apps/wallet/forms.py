import re

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from apps.core.widgets import MoneyInput

from .models import MOBILE_MONEY, DepositRequest, PaymentAccount


class PaymentAccountForm(forms.ModelForm):
    class Meta:
        model = PaymentAccount
        fields = ["method", "number", "holder_name", "bank_name", "label", "is_default"]
        widgets = {"method": forms.RadioSelect,
                   "number": forms.TextInput(attrs={"dir": "ltr", "autocomplete": "off"})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["method"].initial = "bankily"
        if user is not None and not self.instance.pk:
            self.fields["holder_name"].initial = user.full_name
            self.fields["is_default"].initial = not user.payment_accounts.filter(is_active=True).exists()

    def clean(self):
        d = super().clean()
        method, number = d.get("method"), (d.get("number") or "").strip()
        if not method or not number:
            return d
        if method in MOBILE_MONEY:
            from apps.accounts.phones import normalize_phone, region_of

            e164 = normalize_phone(number)
            if region_of(e164) != "MR":
                self.add_error("number", _("Les comptes Bankily, Masrvi et Sedad sont des numéros mauritaniens "
                                           "(8 chiffres)."))
                return d
            d["number"] = e164
        else:
            cleaned = re.sub(r"[\s-]", "", number).upper()
            if not re.fullmatch(r"[A-Z0-9]{10,34}", cleaned):
                self.add_error("number", _("RIB ou IBAN invalide (10 à 34 chiffres ou lettres)."))
                return d
            d["number"] = cleaned
            if not d.get("bank_name"):
                self.add_error("bank_name", _("Indiquez le nom de la banque."))
        if self.user is not None:
            qs = self.user.payment_accounts.filter(is_active=True)
            if qs.filter(method=method, number=d["number"]).exclude(pk=self.instance.pk).exists():
                self.add_error("number", _("Ce compte est déjà enregistré."))
            if not self.instance.pk and qs.count() >= settings.MAX_PAYMENT_ACCOUNTS:
                raise forms.ValidationError(_("Vous avez atteint le nombre maximum de comptes. Retirez-en un d'abord."))
        return d


class AccountChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        label = f"{obj.get_method_display()} · {obj.display_number}"
        if obj.label:
            label += f" · {obj.label}"
        return label


class DepositForm(forms.Form):
    amount = forms.DecimalField(label=_("Montant à déposer (MRU)"), min_value=1, decimal_places=0, widget=MoneyInput())
    account = AccountChoiceField(label=_("Payer depuis"), queryset=PaymentAccount.objects.none(), required=False,
                                 empty_label=None, widget=forms.RadioSelect)
    cash = forms.BooleanField(label=_("Je dépose en espèces dans une agence partenaire"), required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = user.payment_accounts.filter(is_active=True) if user else PaymentAccount.objects.none()
        self.fields["account"].queryset = qs
        default = qs.filter(is_default=True).first() or qs.first()
        if default:
            self.fields["account"].initial = default.pk

    def clean(self):
        d = super().clean()
        if not d.get("cash") and not d.get("account"):
            raise forms.ValidationError(_("Choisissez le compte depuis lequel vous payez, ou le dépôt en espèces."))
        return d


class DepositProofForm(forms.ModelForm):
    class Meta:
        model = DepositRequest
        fields = ["external_ref", "receipt"]
        widgets = {"external_ref": forms.TextInput(attrs={"dir": "ltr"}),
                   "receipt": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["external_ref"].required = True

    def clean_external_ref(self):
        ref = DepositRequest.normalize_ref(self.cleaned_data["external_ref"])
        if DepositRequest.ref_in_use(self.instance.method, ref, exclude_pk=self.instance.pk):
            raise forms.ValidationError(_("Cet identifiant de transaction a déjà été utilisé."))
        return ref


class WithdrawForm(forms.Form):
    amount = forms.DecimalField(label=_("Montant à retirer (MRU)"), min_value=1, decimal_places=0, widget=MoneyInput())
    account = AccountChoiceField(label=_("Recevoir sur"), queryset=PaymentAccount.objects.none(), empty_label=None,
                                 widget=forms.RadioSelect)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = user.payment_accounts.filter(is_active=True) if user else PaymentAccount.objects.none()
        self.fields["account"].queryset = qs
        default = qs.filter(is_default=True).first() or qs.first()
        if default:
            self.fields["account"].initial = default.pk

    def clean_account(self):
        acc = self.cleaned_data["account"]
        if not acc.can_receive_withdrawal:
            raise forms.ValidationError(_(
                "Par sécurité, un nouveau compte peut recevoir un retrait à partir du %(d)s, ou dès qu'un dépôt "
                "depuis ce compte a été confirmé.") % {"d": acc.withdrawable_from.strftime("%d/%m/%Y %H:%M")})
        return acc
