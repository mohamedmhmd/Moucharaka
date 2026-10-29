from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.widgets import MoneyInput

from .models import DepositRequest, PaymentMethod


class DepositForm(forms.Form):
    amount = forms.DecimalField(label=_("Montant à déposer (MRU)"), min_value=1, decimal_places=0, widget=MoneyInput())
    method = forms.ChoiceField(label=_("Moyen de paiement"), choices=PaymentMethod.choices, widget=forms.RadioSelect)


class DepositProofForm(forms.ModelForm):
    class Meta:
        model = DepositRequest
        fields = ["payer_phone", "external_ref", "receipt"]
        widgets = {"payer_phone": forms.TextInput(attrs={"inputmode": "tel", "dir": "ltr"}),
                   "external_ref": forms.TextInput(attrs={"dir": "ltr"}),
                   "receipt": forms.ClearableFileInput(attrs={"accept": "image/*,application/pdf"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["external_ref"].required = True

    def clean_external_ref(self):
        ref = self.cleaned_data["external_ref"].strip()
        if DepositRequest.objects.filter(method=self.instance.method, external_ref=ref).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Cet identifiant de transaction a déjà été utilisé."))
        return ref


class WithdrawForm(forms.Form):
    amount = forms.DecimalField(label=_("Montant à retirer (MRU)"), min_value=1, decimal_places=0, widget=MoneyInput())
    method = forms.ChoiceField(label=_("Recevoir sur"), choices=[c for c in PaymentMethod.choices if c[0] != "cash"],
                               widget=forms.RadioSelect)
    destination = forms.CharField(label=_("Numéro du compte mobile ou RIB"), max_length=60,
                                  widget=forms.TextInput(attrs={"dir": "ltr"}))
