from django.urls import path

from . import views

app_name = "market"

urlpatterns = [
    path("", views.index, name="index"),
    path("mine/", views.mine, name="mine"),
    path("sell/<slug:slug>/", views.sell, name="sell"),
    path("listing/<int:pk>/buy/", views.buy_view, name="buy"),
    path("listing/<int:pk>/cancel/", views.cancel, name="cancel"),
]
