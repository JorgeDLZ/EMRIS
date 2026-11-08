from django.http import HttpResponse
from django.urls import include, path

from apps.accounts.permissions import role_required
from apps.accounts.roles import OPERATOR


@role_required(OPERATOR)
def operator_only(request):
    return HttpResponse("operator")


urlpatterns = [
    path("operator-only/", operator_only, name="operator_only"),
    path("", include("config.urls")),
]
