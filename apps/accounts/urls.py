from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("verify/", views.verify, name="verify"),
    path("register/finish/", views.register_finish, name="register_finish"),
    path("login/", views.login_view, name="login"),
    path("login/whatsapp/", views.otp_login, name="otp_login"),
    path("login/whatsapp/finish/", views.otp_login_finish, name="otp_login_finish"),
    path("logout/", views.logout_view, name="logout"),
    path("password/reset/", views.reset_start, name="reset"),
    path("password/reset/finish/", views.reset_finish, name="reset_finish"),
    path("identity/", views.kyc, name="kyc"),
    path("identity/status/", views.kyc_status, name="kyc_status"),
    path("identity/document/<int:user_id>/<str:field>/", views.kyc_document, name="kyc_document"),
    path("settings/", views.settings_view, name="settings"),
]
