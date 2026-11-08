from django.http import HttpResponse
from django.urls import include, path

from apps.accounts.permissions import role_required
from apps.accounts.roles import ADMINISTRATOR, OPERATOR


@role_required(ADMINISTRATOR)
def protected(request):
    return HttpResponse("protected")


@role_required(OPERATOR)
def operator_only(request):
    return HttpResponse("operator")


urlpatterns = [
    path("accounts/users/", protected, name="protected"),
    path("operator-only/", operator_only, name="operator_only"),
    path("", include("config.urls")),
]
