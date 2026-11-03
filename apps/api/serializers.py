from rest_framework import serializers

from apps.accounts.models import KYCProfile, User
from apps.core.models import Moughataa, Wilaya
from apps.investments.models import Distribution, Holding, Investment
from apps.market.models import Listing, Trade
from apps.projects.models import (BoutiqueProduct, BoutiqueProfile, FinancialReport, Installment, Project, Sector,
                                  UseOfFunds)
from apps.trust.models import TrustScore
from apps.wallet.models import DepositRequest, PaymentAccount, Transaction, Wallet, WithdrawalRequest


class WilayaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wilaya
        fields = ["id", "code", "name_fr", "name_ar"]


class MoughataaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Moughataa
        fields = ["id", "wilaya", "name_fr", "name_ar", "latitude", "longitude"]


class SectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sector
        fields = ["id", "slug", "name_fr", "name_ar"]


class TrustSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrustScore
        fields = ["score", "grade", "has_track_record", "components", "computed_at"]


class PublicUserSerializer(serializers.ModelSerializer):
    trust = TrustSerializer(read_only=True)
    name = serializers.CharField(source="display_name")

    class Meta:
        model = User
        fields = ["public_id", "name", "status", "date_joined", "trust"]


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["public_id", "phone", "full_name", "email", "preferred_language", "status", "date_joined"]
        read_only_fields = ["public_id", "phone", "full_name", "status", "date_joined"]


class KYCSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYCProfile
        exclude = ["user", "review_notes", "reviewed_by", "risk_level"]
        read_only_fields = ["status", "rejection_reason", "submitted_at", "reviewed_at", "terms_accepted_at"]


class UseOfFundsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UseOfFunds
        fields = ["category", "label", "amount"]


class ProjectListSerializer(serializers.ModelSerializer):
    sector = SectorSerializer(read_only=True)
    wilaya = serializers.CharField(source="wilaya.name_fr", allow_null=True, default=None)
    moughataa = serializers.CharField(source="moughataa.name_fr", allow_null=True, default=None)
    total_shares = serializers.IntegerField(read_only=True)
    funding_pct = serializers.IntegerField(read_only=True)
    headline_return = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["slug", "reference", "title", "tagline", "kind", "financing_model", "status", "sector", "wilaya",
                  "moughataa", "cover", "target_amount", "share_price", "total_shares", "shares_sold",
                  "raised_amount", "funding_pct", "investors_count", "campaign_end", "duration_months",
                  "projected_annual_return_pct", "margin_pct", "risk_grade", "headline_return"]

    def get_headline_return(self, obj):
        v = obj.headline_return()
        return str(v) if v is not None else None


class BoutiqueSerializer(serializers.ModelSerializer):
    declared_monthly_revenue = serializers.DecimalField(max_digits=14, decimal_places=0, read_only=True)
    fixed_costs = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = BoutiqueProfile
        exclude = ["id", "project"]


class ProductSerializer(serializers.ModelSerializer):
    margin_pct = serializers.DecimalField(max_digits=6, decimal_places=1, read_only=True)

    class Meta:
        model = BoutiqueProduct
        fields = ["name", "unit", "buy_price", "sell_price", "monthly_units", "margin_pct"]


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialReport
        fields = ["period_start", "period_end", "revenue", "cogs", "expenses", "net_profit", "inventory_value",
                  "cash_balance", "status", "submitted_at", "due_date"]


class InstallmentSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Installment
        fields = ["number", "due_date", "principal", "margin", "amount", "status", "paid_at"]


class DistributionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Distribution
        fields = ["kind", "gross_amount", "platform_fee", "net_amount", "per_share", "shares_outstanding",
                  "shares_retired", "paid_at", "on_time", "note"]


class ProjectDetailSerializer(ProjectListSerializer):
    owner = PublicUserSerializer(read_only=True)
    uses_of_funds = UseOfFundsSerializer(many=True, read_only=True)
    boutique = BoutiqueSerializer(read_only=True)
    boutique_products = ProductSerializer(many=True, read_only=True)
    reports = ReportSerializer(many=True, read_only=True)
    installments = InstallmentSerializer(many=True, read_only=True)
    distributions = DistributionSerializer(many=True, read_only=True)
    model = serializers.SerializerMethodField()

    class Meta(ProjectListSerializer.Meta):
        fields = ProjectListSerializer.Meta.fields + [
            "description", "neighborhood", "owner", "min_shares", "min_funding_pct", "owner_contribution",
            "investor_profit_share_pct", "distribution_frequency", "exit_mode", "repayment_mode", "guarantee",
            "review_notes", "success_fee_pct", "management_fee_pct", "campaign_start", "uses_of_funds", "boutique",
            "boutique_products", "reports", "installments", "distributions", "model", "trading_enabled"]

    def get_model(self, obj):
        b = getattr(obj, "boutique", None)
        if not b:
            return None
        to_str = lambda d: {k: str(v) for k, v in d.items()}  # noqa: E731
        return {"scenarios": {k: to_str(v) for k, v in b.scenarios().items()},
                "indicators": [{**i, "label": str(i["label"]), "hint": str(i["hint"]), "unit": str(i["unit"]),
                                "value": str(i["value"])} for i in b.indicators()]}


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ["balance", "held", "updated_at"]


class TransactionSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display")
    project = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Transaction
        fields = ["reference", "kind", "kind_label", "amount", "held_delta", "balance_after", "description",
                  "project", "created_at"]


class PaymentAccountSerializer(serializers.ModelSerializer):
    display_number = serializers.CharField(read_only=True)
    can_receive_withdrawal = serializers.BooleanField(read_only=True)
    withdrawable_from = serializers.DateTimeField(read_only=True)

    class Meta:
        model = PaymentAccount
        fields = ["id", "method", "number", "display_number", "holder_name", "bank_name", "label", "is_default",
                  "verified_at", "can_receive_withdrawal", "withdrawable_from", "created_at"]
        read_only_fields = ["verified_at", "created_at"]


class DepositSerializer(serializers.ModelSerializer):
    account = serializers.PrimaryKeyRelatedField(source="payment_account", queryset=PaymentAccount.objects.none(),
                                                 required=False, allow_null=True)

    class Meta:
        model = DepositRequest
        fields = ["reference", "amount", "method", "account", "external_ref", "status", "created_at"]
        read_only_fields = ["reference", "method", "status", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        req = self.context.get("request")
        if req and req.user.is_authenticated:
            self.fields["account"].queryset = req.user.payment_accounts.filter(is_active=True)


class WithdrawalSerializer(serializers.ModelSerializer):
    account = serializers.PrimaryKeyRelatedField(source="payment_account", queryset=PaymentAccount.objects.none())

    class Meta:
        model = WithdrawalRequest
        fields = ["reference", "amount", "fee", "account", "method", "destination", "status", "created_at"]
        read_only_fields = ["reference", "fee", "method", "destination", "status", "created_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        req = self.context.get("request")
        if req and req.user.is_authenticated:
            self.fields["account"].queryset = req.user.payment_accounts.filter(is_active=True)


class HoldingSerializer(serializers.ModelSerializer):
    project = ProjectListSerializer(read_only=True)
    free_shares = serializers.IntegerField(read_only=True)

    class Meta:
        model = Holding
        fields = ["project", "shares", "locked_shares", "free_shares", "cost_basis", "received_total"]


class InvestmentSerializer(serializers.ModelSerializer):
    project = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Investment
        fields = ["id", "project", "shares", "amount", "status", "created_at", "settled_at"]


class ListingSerializer(serializers.ModelSerializer):
    project = serializers.SlugRelatedField(slug_field="slug", queryset=Project.objects.all())
    seller = serializers.CharField(source="seller.display_name", read_only=True)
    premium_pct = serializers.DecimalField(max_digits=8, decimal_places=1, read_only=True)

    class Meta:
        model = Listing
        fields = ["id", "project", "seller", "shares", "remaining", "price_per_share", "premium_pct", "allow_partial",
                  "note", "status", "created_at", "expires_at"]
        read_only_fields = ["remaining", "status", "created_at", "expires_at"]


class TradeSerializer(serializers.ModelSerializer):
    project = serializers.SlugRelatedField(slug_field="slug", read_only=True)

    class Meta:
        model = Trade
        fields = ["project", "shares", "price_per_share", "gross", "created_at"]
