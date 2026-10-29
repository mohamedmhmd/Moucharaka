from django.urls import path

from . import views

app_name = "trust"

urlpatterns = [
    path("u/<str:public_id>/", views.public_profile, name="profile"),
    path("trust-score/", views.score_method, name="method"),
]
