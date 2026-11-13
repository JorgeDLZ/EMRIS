from django.shortcuts import render

from apps.accounts.permissions import role_required
from apps.accounts.roles import ALL_ROLES
from apps.emergencies.policies import visible_emergencies

from .summary import emergency_summary


@role_required(*ALL_ROLES)
def index(request):
    summary = emergency_summary(visible_emergencies(request.user))
    return render(request, "dashboard/dashboard.html", {"summary": summary})
