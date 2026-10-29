from django.urls import path

from . import views

app_name = "staff"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("kyc/", views.kyc_list, name="kyc_list"),
    path("kyc/<int:pk>/", views.kyc_review, name="kyc_review"),
    path("projects/", views.project_list, name="project_list"),
    path("projects/<int:pk>/", views.project_review, name="project_review"),
    path("projects/<int:pk>/<str:action>/", views.project_action, name="project_action"),
    path("deposits/", views.deposits, name="deposits"),
    path("withdrawals/", views.withdrawals, name="withdrawals"),
    path("reports/", views.reports, name="reports"),
]
