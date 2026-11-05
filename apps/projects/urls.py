from django.urls import path

from . import sharing, views

app_name = "projects"

urlpatterns = [
    path("", views.explore, name="explore"),
    path("new/", views.new_project, name="new"),
    path("new/details/", views.new_basics, name="new_basics"),
    path("document/<int:pk>/", views.document, name="document"),
    path("report-file/<int:pk>/", views.report_attachment, name="report_attachment"),
    path("investment/<int:pk>/cancel/", views.cancel_investment_view, name="cancel_investment"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<slug:slug>/qr.svg", sharing.qr_svg, name="qr"),
    path("<slug:slug>/poster/", sharing.poster, name="poster"),
    path("<slug:slug>/interest/", sharing.register_interest, name="interest"),
    path("<slug:slug>/invest/", views.invest_view, name="invest"),
    path("<slug:slug>/favorite/", views.toggle_favorite, name="favorite"),
    path("<slug:slug>/ask/", views.ask_question, name="ask"),
    path("<slug:slug>/review/", views.review_view, name="review"),
    path("<slug:slug>/edit/", views.edit_project, {"step": "basics"}, name="edit_start"),
    path("<slug:slug>/edit/<str:step>/", views.edit_project, name="edit"),
    path("<slug:slug>/delete/", views.delete_draft, name="delete"),
    path("<slug:slug>/manage/", views.manage, name="manage"),
    path("<slug:slug>/manage/report/", views.submit_report_view, name="submit_report"),
    path("<slug:slug>/manage/distribute/<int:report_id>/", views.pay_distribution_view, name="pay_distribution"),
    path("<slug:slug>/manage/installment/<int:inst_id>/", views.pay_installment_view, name="pay_installment"),
    path("<slug:slug>/manage/buyback/", views.buyback_view, name="buyback"),
    path("<slug:slug>/manage/settle/", views.settle_view, name="settle"),
    path("<slug:slug>/manage/settle/<int:pk>/cancel/", views.cancel_settlement_view, name="cancel_settlement"),
    path("<slug:slug>/manage/update/", views.post_update, name="post_update"),
    path("<slug:slug>/manage/answer/<int:qid>/", views.answer_question, name="answer"),
    path("<slug:slug>/manage/feature/", views.feature_project, name="feature"),
]
