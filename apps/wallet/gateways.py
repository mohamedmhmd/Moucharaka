"""Payment gateways.

Mauritanian mobile-money operators (Bankily, Masrvi, Sedad…) give merchant
APIs only under contract, so the default gateway is *assisted manual*: the
user pays the platform's merchant number with the deposit reference, then
types the transaction id; staff (or a webhook) confirms.

To plug a real API, subclass `Gateway`, implement `initiate()` (return a
redirect URL or instructions) and have the provider call the webhook
`/wallet/webhook/<method>/`, signed with HMAC-SHA256 of the raw body using
PAYMENT_WEBHOOK_SECRET in the `X-Signature` header. Register the class in
GATEWAYS below.
"""
import hashlib
import hmac

from django.conf import settings
from django.utils.translation import gettext as _

from apps.core.models import PlatformSettings


class Gateway:
    method = None
    automatic = False

    def instructions(self, deposit):
        raise NotImplementedError

    def initiate(self, deposit):
        """Return a URL to redirect the payer to, or None for manual flows."""
        return None


class MobileMoneyManual(Gateway):
    merchant_field = None
    app_name = ""

    def instructions(self, deposit):
        number = getattr(PlatformSettings.get(), self.merchant_field, "") or "—"
        return [
            _("Ouvrez l'application %(app)s.") % {"app": self.app_name},
            _("Payez %(amount)s MRU au marchand %(number)s.") % {
                "amount": f"{deposit.amount:,.0f}".replace(",", " "), "number": number},
            _("Indiquez la référence %(ref)s dans le motif si l'application le permet.") % {"ref": deposit.reference},
            _("Recopiez ci-dessous l'identifiant de transaction reçu par SMS et ajoutez une capture du reçu."),
        ]


class BankilyGateway(MobileMoneyManual):
    method, merchant_field, app_name = "bankily", "merchant_bankily", "Bankily"


class MasrviGateway(MobileMoneyManual):
    method, merchant_field, app_name = "masrvi", "merchant_masrvi", "Masrvi"


class SedadGateway(MobileMoneyManual):
    method, merchant_field, app_name = "sedad", "merchant_sedad", "Sedad"


class BankTransferGateway(Gateway):
    method = "bank"

    def instructions(self, deposit):
        return [
            _("Faites un virement de %(amount)s MRU vers :") % {"amount": f"{deposit.amount:,.0f}".replace(",", " ")},
            PlatformSettings.get().bank_details or "—",
            _("Motif obligatoire : %(ref)s") % {"ref": deposit.reference},
            _("Ajoutez ensuite l'avis de virement ci-dessous."),
        ]


class CashGateway(Gateway):
    method = "cash"

    def instructions(self, deposit):
        return [
            _("Présentez-vous dans une agence partenaire avec votre pièce d'identité."),
            _("Donnez la référence %(ref)s et le montant %(amount)s MRU.") % {
                "ref": deposit.reference, "amount": f"{deposit.amount:,.0f}".replace(",", " ")},
            _("L'agent confirme le dépôt ; votre solde est crédité immédiatement."),
        ]


GATEWAYS = {g.method: g() for g in (BankilyGateway, MasrviGateway, SedadGateway, BankTransferGateway, CashGateway)}


def get_gateway(method):
    return GATEWAYS[method]


def verify_signature(raw_body: bytes, signature: str) -> bool:
    secret = settings.PAYMENT_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())
