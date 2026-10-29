from django.urls import path

from . import views

app_name = "wallet"

urlpatterns = [
    path("", views.home, name="home"),
    path("deposit/", views.deposit, name="deposit"),
    path("deposit/<str:ref>/", views.deposit_detail, name="deposit_detail"),
    path("deposit/<str:ref>/receipt/", views.receipt, name="receipt"),
    path("withdraw/", views.withdraw, name="withdraw"),
    path("withdraw/<str:ref>/cancel/", views.withdraw_cancel, name="withdraw_cancel"),
    path("webhook/<str:method>/", views.webhook, name="webhook"),
]
