from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path, re_path
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse
from django.views.static import serve


def healthz(request):
    return HttpResponse("ok")


admin.site.site_header = _("Moucharaka — administration")
admin.site.site_title = "Moucharaka"
admin.site.index_title = _("Pilotage de la plateforme")

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("api/v1/", include("apps.api.urls")),
    path("healthz", healthz),
]

from apps.projects import sharing  # noqa: E402

urlpatterns += i18n_patterns(
    path("s/<str:ref>/", sharing.short_link, name="short"),
    path("search/", sharing.search, name="search"),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("projects/", include("apps.projects.urls")),
    path("wallet/", include("apps.wallet.urls")),
    path("market/", include("apps.market.urls")),
    path("staff/", include("apps.staff.urls")),
    path("", include("apps.trust.urls")),
    path("admin/", admin.site.urls),
    prefix_default_language=False,
)

if settings.SERVE_MEDIA:
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]
