from django.urls import path

from . import views

app_name = "contracts"
urlpatterns = [
    path("", views.mine, name="mine"),
    path("<str:ref>/", views.detail, name="detail"),
    path("<str:ref>/sign/", views.sign_view, name="sign"),
]
