from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import role_required
from apps.accounts.roles import CAPABILITIES
from apps.dashboard.exports import (
    HISTORY_HEADER,
    history_rows,
    is_high_impact_record,
    xlsx_response,
)
from apps.emergencies.models import EmergencyType
from apps.places.models import Department
from apps.plans.models import ACTION_CODE_CHOICES

from .filters import HISTORY_PAGE_SIZE, filter_records, querystring
from .models import UngrdRecord


@role_required(*CAPABILITIES["browse_history"])
def record_list(request):
    records, cleaned = filter_records(request.GET)
    page = Paginator(records, HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "history/record_list.html",
        {
            "page": page,
            "cleaned": cleaned,
            "querystring": querystring(cleaned),
            "emergency_types": EmergencyType.objects.order_by("name"),
            "departments": Department.objects.order_by("name"),
        },
    )


@role_required(*CAPABILITIES["browse_history"])
def export(request):
    records, _ = filter_records(request.GET)
    return xlsx_response(
        "ungrd_history.xlsx",
        "UNGRD history",
        HISTORY_HEADER,
        history_rows(records),
        is_high_impact_record,
    )


@role_required(*CAPABILITIES["browse_history"])
def record_detail(request, source_row):
    record = get_object_or_404(
        UngrdRecord.objects.select_related("emergency_type", "department", "municipality"),
        source_row=source_row,
    )
    labels = dict(ACTION_CODE_CHOICES)
    actions = [labels.get(code, code) for code in record.action_codes]
    return render(request, "history/record_detail.html", {"record": record, "actions": actions})
