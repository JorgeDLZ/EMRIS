from django.db import OperationalError, connection
from django.http import JsonResponse
from django.views.generic import TemplateView

from apps.accounts.permissions import RoleRequiredMixin


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


class HomeView(RoleRequiredMixin, TemplateView):
    template_name = "home.html"


home = HomeView.as_view()
