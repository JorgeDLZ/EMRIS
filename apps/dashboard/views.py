from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.permissions import has_role, role_required
from apps.accounts.roles import ALL_ROLES, EDIT_ROLES
from apps.emergencies.policies import visible_emergencies

from .ranking import departments, in_department, risk_ranking
from .summary import emergency_summary, seismic_activity

PAGE_SIZE = 50
TOP_SIZE = 10


@role_required(*ALL_ROLES)
def index(request):
    summary = emergency_summary(visible_emergencies(request.user))
    context = {
        "summary": summary,
        "seismic": seismic_activity(),
        "show_ranking": has_role(request.user, *EDIT_ROLES),
    }
    if context["show_ranking"]:
        ranking = risk_ranking()
        context["ranking"] = ranking
        context["top_rows"] = ranking.rows[:TOP_SIZE]
    return render(request, "dashboard/dashboard.html", context)


@role_required(*EDIT_ROLES)
def ranking(request):
    full = risk_ranking()
    department = request.GET.get("department", "")
    rows = [row for row in full.rows if in_department(row, department)]
    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "dashboard/ranking.html",
        {
            "ranking": full,
            "page": page,
            "department": department,
            "departments": departments(full.rows),
        },
    )
