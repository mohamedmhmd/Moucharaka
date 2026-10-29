from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("projects", views.ProjectViewSet, basename="project")
router.register("market/listings", views.ListingViewSet, basename="listing")
router.register("wallet/deposits", views.DepositViewSet, basename="deposit")

app_name = "api"

urlpatterns = [
    path("auth/otp/request", views.otp_request),
    path("auth/otp/verify", views.otp_verify),
    path("auth/register", views.register),
    path("auth/reset", views.reset_password),
    path("auth/token", views.token),
    path("auth/kyc", views.KYCView.as_view()),
    path("me", views.MeView.as_view()),
    path("reference", views.reference),
    path("wallet", views.wallet),
    path("wallet/withdraw/otp", views.withdraw_otp),
    path("wallet/withdraw", views.withdraw),
    path("portfolio", views.portfolio),
    path("users/<str:public_id>", views.public_profile),
    path("projects/<slug:slug>/trades", views.trades),
    path("", include(router.urls)),
]
