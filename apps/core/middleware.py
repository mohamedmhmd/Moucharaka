from django.http import HttpResponse


class HealthCheckMiddleware:
    """Answer /healthz before host validation and the HTTPS redirect.

    Load balancers (Render, Railway, Kubernetes…) probe the app over plain HTTP
    with an internal Host header, which ALLOWED_HOSTS and SECURE_SSL_REDIRECT
    would otherwise reject or redirect.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in ("/healthz", "/healthz/"):
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
