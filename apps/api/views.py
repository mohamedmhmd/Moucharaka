"""REST API v1 (token auth) for mobile apps and partners.

Auth flow for a new user:
    POST /api/v1/auth/otp/request   {"phone": "22123456", "purpose": "register"}
    POST /api/v1/auth/otp/verify    {"phone": ..., "purpose": ..., "code": "123456"} → {"verification": "<signed>"}
    POST /api/v1/auth/register      {"verification": ..., "full_name": ..., "password": ...} → {"token": ...}
    POST /api/v1/auth/kyc           multipart KYC fields + files
Existing user:
    POST /api/v1/auth/token         {"phone": ..., "password": ...} → {"token": ...}
Send `Authorization: Token <token>` on every call.
"""
from django.contrib.auth import authenticate, password_validation
from django.core import signing
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from apps.accounts.models import KYCProfile, PhoneOTP, User, normalize_phone, phone_validator
from apps.accounts.otp import OTPError, issue_otp, verify_otp
from apps.core.models import Moughataa, Wilaya
from apps.core.utils import client_ip
from apps.investments.models import Holding, Investment
from apps.investments.services import InvestmentError, invest
from apps.market.models import Listing, Trade
from apps.market.services import MarketError, buy, cancel_listing, create_listing
from apps.projects.models import Project, Sector
from apps.wallet.models import DepositRequest, Wallet
from apps.wallet.gateways import get_gateway
from apps.wallet.services import WalletError, request_withdrawal

from . import serializers as S

SIGN_SALT = "api-phone-verification"


class IsApproved(permissions.BasePermission):
    message = "Account not verified by the compliance team yet."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_approved)


# ------------------------------------------------------------------ auth

@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def otp_request(request):
    phone = normalize_phone(request.data.get("phone"))
    purpose = request.data.get("purpose", "register")
    try:
        phone_validator(phone)
    except ValidationError:
        raise DRFValidationError({"phone": _("Numéro invalide.")})
    if purpose not in ("register", "login", "reset"):
        raise DRFValidationError({"purpose": "register | login | reset"})
    exists = User.objects.filter(phone=phone).exists()
    if purpose == "register" and exists:
        raise DRFValidationError({"phone": _("Ce numéro a déjà un compte. Connectez-vous.")})
    if purpose != "register" and not exists:
        return Response({"sent": True})  # no account enumeration
    try:
        issue_otp(phone, purpose, ip=client_ip(request))
    except OTPError as e:
        return Response({"detail": str(e)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    return Response({"sent": True})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def otp_verify(request):
    phone = normalize_phone(request.data.get("phone"))
    purpose = request.data.get("purpose", "register")
    try:
        verify_otp(phone, purpose, request.data.get("code", ""))
    except OTPError as e:
        raise DRFValidationError({"code": str(e)})
    if purpose == "login":
        user = get_object_or_404(User, phone=phone, is_active=True)
        token, _c = Token.objects.get_or_create(user=user)
        return Response({"token": token.key})
    return Response({"verification": signing.dumps({"phone": phone, "purpose": purpose}, salt=SIGN_SALT)})


def _read_verification(value, purpose):
    try:
        data = signing.loads(value or "", salt=SIGN_SALT, max_age=15 * 60)
    except signing.BadSignature:
        raise DRFValidationError({"verification": _("Vérification expirée, recommencez.")})
    if data.get("purpose") != purpose:
        raise DRFValidationError({"verification": "wrong purpose"})
    return data["phone"]


def _check_password(pwd, user=None):
    try:
        password_validation.validate_password(pwd, user)
    except ValidationError as e:
        raise DRFValidationError({"password": list(e.messages)})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def register(request):
    phone = _read_verification(request.data.get("verification"), "register")
    if User.objects.filter(phone=phone).exists():
        raise DRFValidationError({"phone": _("Ce numéro a déjà un compte. Connectez-vous.")})
    full_name = (request.data.get("full_name") or "").strip()
    if len(full_name) < 3:
        raise DRFValidationError({"full_name": _("Nom complet requis.")})
    pwd = request.data.get("password") or ""
    _check_password(pwd)
    user = User.objects.create_user(phone, pwd, full_name=full_name, phone_verified_at=timezone.now(),
                                    preferred_language=request.data.get("language", "ar"))
    token, _c = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": S.MeSerializer(user).data}, status=201)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def reset_password(request):
    phone = _read_verification(request.data.get("verification"), "reset")
    user = get_object_or_404(User, phone=phone)
    pwd = request.data.get("password") or ""
    _check_password(pwd, user)
    user.set_password(pwd)
    user.save(update_fields=["password"])
    Token.objects.filter(user=user).delete()
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def token(request):
    user = authenticate(request, phone=request.data.get("phone"), password=request.data.get("password"))
    if not user or user.status == User.Status.SUSPENDED:
        return Response({"detail": _("Numéro ou mot de passe incorrect.")}, status=400)
    tok, _c = Token.objects.get_or_create(user=user)
    return Response({"token": tok.key, "user": S.MeSerializer(user).data})


class KYCView(generics.RetrieveUpdateAPIView):
    serializer_class = S.KYCSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return KYCProfile.objects.filter(user=self.request.user).first()

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        return Response(S.KYCSerializer(obj).data if obj else None)

    def update(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj and obj.status in ("submitted", "approved"):
            return Response({"detail": _("Dossier déjà soumis.")}, status=409)
        ser = S.KYCSerializer(obj, data=request.data, partial=bool(obj))
        ser.is_valid(raise_exception=True)
        profile = ser.save(user=request.user, status="submitted", submitted_at=timezone.now(),
                           terms_accepted_at=timezone.now())
        try:
            profile.full_clean(exclude=["user"])
        except ValidationError as e:
            raise DRFValidationError(e.message_dict)
        request.user.status = User.Status.PENDING
        request.user.save(update_fields=["status"])
        return Response(S.KYCSerializer(profile).data)

    post = update


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = S.MeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


# ------------------------------------------------------------------ reference data

@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def reference(request):
    return Response({
        "wilayas": S.WilayaSerializer(Wilaya.objects.all(), many=True).data,
        "moughataas": S.MoughataaSerializer(Moughataa.objects.all(), many=True).data,
        "sectors": S.SectorSerializer(Sector.objects.all(), many=True).data,
        "kinds": dict(Project._meta.get_field("kind").choices),
        "financing_models": dict(Project._meta.get_field("financing_model").choices),
    })


# ------------------------------------------------------------------ projects

class ProjectViewSet(viewsets.ReadOnlyModelViewSet):
    lookup_field = "slug"
    filterset_fields = ["kind", "financing_model", "status", "wilaya", "sector"]
    search_fields = ["title", "tagline", "neighborhood", "reference", "boutique__shop_name", "owner__full_name",
                     "owner__public_id"]
    ordering_fields = ["campaign_end", "raised_amount", "projected_annual_return_pct", "created_at"]

    def get_queryset(self):
        return Project.objects.filter(status__in=Project.PUBLIC_STATUSES).select_related(
            "sector", "wilaya", "moughataa", "owner", "owner__trust")

    def get_serializer_class(self):
        return S.ProjectDetailSerializer if self.action == "retrieve" else S.ProjectListSerializer

    @action(detail=True, methods=["post"], permission_classes=[IsApproved])
    def invest(self, request, slug=None):
        project = self.get_object()
        try:
            inv = invest(request.user, project, int(request.data.get("shares", 0)),
                         bool(request.data.get("risk_acknowledged")))
        except (InvestmentError, ValueError) as e:
            return Response({"detail": str(e)}, status=400)
        return Response(S.InvestmentSerializer(inv).data, status=201)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def public_profile(request, public_id):
    from apps.trust.services import get_score

    user = get_object_or_404(User, public_id=public_id, is_active=True)
    get_score(user)
    projects = Project.objects.filter(owner=user, status__in=Project.PUBLIC_STATUSES)
    return Response({"user": S.PublicUserSerializer(user).data,
                     "projects": S.ProjectListSerializer(projects, many=True).data})


# ------------------------------------------------------------------ wallet & portfolio

@api_view(["GET"])
@permission_classes([IsApproved])
def wallet(request):
    w = Wallet.for_user(request.user)
    txs = w.transactions.select_related("project")[:50]
    return Response({"wallet": S.WalletSerializer(w).data, "transactions": S.TransactionSerializer(txs, many=True).data})


class DepositViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = S.DepositSerializer
    permission_classes = [IsApproved]

    def get_queryset(self):
        return DepositRequest.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        acc = ser.validated_data.get("payment_account")
        dep = ser.save(user=request.user, method=acc.method if acc else "cash",
                       payer_phone=acc.number if acc else request.user.phone,
                       status="proof" if ser.validated_data.get("external_ref") else "pending")
        return Response({**S.DepositSerializer(dep).data,
                         "instructions": [str(s) for s in get_gateway(dep.method).instructions(dep)]}, status=201)


class PaymentAccountViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin,
                            viewsets.GenericViewSet):
    """Mobile-money and bank accounts used for deposits and withdrawals."""

    serializer_class = S.PaymentAccountSerializer
    permission_classes = [IsApproved]

    def get_queryset(self):
        return self.request.user.payment_accounts.filter(is_active=True)

    def create(self, request, *args, **kwargs):
        from apps.wallet.forms import PaymentAccountForm
        from apps.wallet.services import save_payment_account

        form = PaymentAccountForm(request.data, user=request.user)
        if not form.is_valid():
            return Response(form.errors, status=400)
        acc = save_payment_account(request.user, form, request=request)
        return Response(S.PaymentAccountSerializer(acc).data, status=201)

    def destroy(self, request, *args, **kwargs):
        from apps.wallet.services import remove_payment_account

        try:
            remove_payment_account(self.get_object(), request=request)
        except WalletError as e:
            return Response({"detail": str(e)}, status=409)
        return Response(status=204)


@api_view(["POST"])
@permission_classes([IsApproved])
def withdraw(request):
    ser = S.WithdrawalSerializer(data=request.data, context={"request": request})
    ser.is_valid(raise_exception=True)
    try:
        verify_otp(request.user.phone, PhoneOTP.Purpose.WITHDRAW, request.data.get("code", ""))
    except OTPError as e:
        return Response({"code": str(e), "hint": "POST /api/v1/wallet/withdraw/otp first"}, status=400)
    try:
        wr = request_withdrawal(request.user, ser.validated_data["amount"], ser.validated_data["payment_account"])
    except WalletError as e:
        return Response({"detail": str(e)}, status=400)
    return Response(S.WithdrawalSerializer(wr).data, status=201)


@api_view(["POST"])
@permission_classes([IsApproved])
@throttle_classes([])
def withdraw_otp(request):
    try:
        issue_otp(request.user.phone, PhoneOTP.Purpose.WITHDRAW, ip=client_ip(request))
    except OTPError as e:
        return Response({"detail": str(e)}, status=429)
    return Response({"sent": True})


@api_view(["GET"])
@permission_classes([IsApproved])
def portfolio(request):
    holdings = Holding.objects.filter(user=request.user, shares__gt=0).select_related("project", "project__sector",
                                                                                      "project__wilaya", "project__moughataa")
    invs = Investment.objects.filter(investor=request.user).select_related("project")[:100]
    return Response({"holdings": S.HoldingSerializer(holdings, many=True).data,
                     "investments": S.InvestmentSerializer(invs, many=True).data})


# ------------------------------------------------------------------ market

class ListingViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                     mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = S.ListingSerializer
    filterset_fields = ["project__slug"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.AllowAny()]
        return [IsApproved()]

    def get_queryset(self):
        qs = Listing.objects.select_related("project", "seller")
        if self.action in ("list", "retrieve", "buy"):
            return qs.filter(status="active")
        return qs.filter(Q(seller=self.request.user))

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            listing = create_listing(request.user, d["project"], d["shares"], d["price_per_share"],
                                     d.get("allow_partial", True), d.get("note", ""))
        except MarketError as e:
            return Response({"detail": str(e)}, status=400)
        return Response(S.ListingSerializer(listing).data, status=201)

    def destroy(self, request, *args, **kwargs):
        listing = self.get_object()
        cancel_listing(listing, user=request.user)
        return Response(status=204)

    @action(detail=True, methods=["post"])
    def buy(self, request, pk=None):
        listing = self.get_object()
        try:
            trade = buy(request.user, listing, int(request.data.get("shares", listing.remaining)))
        except (MarketError, ValueError) as e:
            return Response({"detail": str(e)}, status=400)
        return Response(S.TradeSerializer(trade).data, status=201)


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def trades(request, slug):
    project = get_object_or_404(Project, slug=slug, status__in=Project.PUBLIC_STATUSES)
    return Response(S.TradeSerializer(Trade.objects.filter(project=project)[:200], many=True).data)
