from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("portfolio/", views.portfolio, name="portfolio"),
    path("notifications/", views.notifications, name="notifications"),
    path("p/<str:name>/", views.page, name="page"),
]
