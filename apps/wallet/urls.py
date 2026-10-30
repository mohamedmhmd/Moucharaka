from django.urls import path

from . import views

app_name = "wallet"

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/", views.accounts, name="accounts"),
    path("accounts/add/", views.account_add, name="account_add"),
    path("accounts/<int:pk>/edit/", views.account_add, name="account_edit"),
    path("accounts/<int:pk>/default/", views.account_default, name="account_default"),
    path("accounts/<int:pk>/remove/", views.account_remove, name="account_remove"),
    path("deposit/", views.deposit, name="deposit"),
    path("deposit/<str:ref>/", views.deposit_detail, name="deposit_detail"),
    path("deposit/<str:ref>/receipt/", views.receipt, name="receipt"),
    path("withdraw/", views.withdraw, name="withdraw"),
    path("withdraw/<str:ref>/cancel/", views.withdraw_cancel, name="withdraw_cancel"),
    path("webhook/<str:method>/", views.webhook, name="webhook"),
]
