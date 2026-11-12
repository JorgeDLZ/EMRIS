from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import role_required
from apps.accounts.roles import ADMINISTRATOR, ALL_ROLES, RISK_MANAGER
from ml.text import normalize_name

from .forms import EmergencyForm, EmergencyTypeForm, ImpactForm
from .models import STATUS_CHOICES, Emergency, EmergencyType, Impact
from .policies import EDIT_ROLES, allowed_statuses, can_edit_emergency, visible_emergencies
from .workflow import LABELS, WorkflowError, add_note, change_status, create_emergency, save_impact

PAGE_SIZE = 25


def _editable_emergency(user, pk):
    emergency = get_object_or_404(
        visible_emergencies(user).select_related("emergency_type", "municipality__department"),
        pk=pk,
    )
    if not can_edit_emergency(user, emergency):
        raise PermissionDenied
    return emergency


@role_required(ADMINISTRATOR, RISK_MANAGER)
def type_list(request):
    return render(request, "emergencies/type_list.html", {"types": EmergencyType.objects.all()})


@role_required(ADMINISTRATOR, RISK_MANAGER)
def type_create(request):
    form = EmergencyTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        emergency_type = form.save()
        messages.success(request, f"{emergency_type.name} was added.")
        return redirect("emergencies:type_list")
    return render(request, "emergencies/type_form.html", {"form": form, "emergency_type": None})


@role_required(ADMINISTRATOR, RISK_MANAGER)
def type_edit(request, pk):
    emergency_type = get_object_or_404(EmergencyType, pk=pk)
    form = EmergencyTypeForm(request.POST or None, instance=emergency_type)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{emergency_type.name} was updated.")
        return redirect("emergencies:type_list")
    return render(request, "emergencies/type_form.html", {"form": form, "emergency_type": emergency_type})


@role_required(*ALL_ROLES)
def emergency_list(request):
    emergencies = visible_emergencies(request.user).select_related(
        "emergency_type", "municipality__department"
    )

    status = request.GET.get("status", "")
    if status in LABELS:
        emergencies = emergencies.filter(status=status)
    else:
        status = ""

    type_id = request.GET.get("type", "")
    if type_id.isdigit():
        emergencies = emergencies.filter(emergency_type_id=int(type_id))
    else:
        type_id = ""

    query = request.GET.get("q", "").strip()
    if query:
        emergencies = emergencies.filter(municipality__name_key__icontains=normalize_name(query))

    page = Paginator(emergencies, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "emergencies/emergency_list.html",
        {
            "page": page,
            "status": status,
            "type_id": type_id,
            "query": query,
            "status_choices": STATUS_CHOICES,
            "types": EmergencyType.objects.all(),
        },
    )


@role_required(*EDIT_ROLES)
def emergency_create(request):
    form = EmergencyForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        emergency = create_emergency(request.user, **form.cleaned_data)
        messages.success(request, "The emergency was reported.")
        return redirect("emergencies:emergency_detail", pk=emergency.pk)
    return render(request, "emergencies/emergency_form.html", {"form": form, "emergency": None})


@role_required(*ALL_ROLES)
def emergency_detail(request, pk):
    emergency = get_object_or_404(
        visible_emergencies(request.user).select_related(
            "emergency_type", "municipality__department", "seismic_event"
        ),
        pk=pk,
    )
    user = request.user
    log = list(emergency.status_log.select_related("author"))
    for entry in log:
        entry.status_label = LABELS.get(entry.status, entry.status)
    return render(
        request,
        "emergencies/emergency_detail.html",
        {
            "emergency": emergency,
            "impact": Impact.objects.filter(emergency=emergency).first(),
            "log": log,
            "plan": getattr(emergency, "action_plan", None),
            "can_edit": can_edit_emergency(user, emergency),
            "next_statuses": [(status, LABELS[status]) for status in allowed_statuses(user, emergency)],
        },
    )


@transaction.atomic
def _save_emergency_fields(user, emergency, form):
    locked = Emergency.objects.select_for_update().get(pk=emergency.pk)
    if not can_edit_emergency(user, locked):
        raise PermissionDenied
    fields = EmergencyForm.Meta.fields
    for name in fields:
        setattr(locked, name, getattr(form.instance, name))
    locked.save(update_fields=[*fields, "updated_at"])


@role_required(*EDIT_ROLES)
def emergency_edit(request, pk):
    emergency = _editable_emergency(request.user, pk)
    form = EmergencyForm(request.POST or None, instance=emergency, user=request.user)
    if request.method == "POST" and form.is_valid():
        _save_emergency_fields(request.user, emergency, form)
        messages.success(request, "The emergency was updated.")
        return redirect("emergencies:emergency_detail", pk=emergency.pk)
    return render(request, "emergencies/emergency_form.html", {"form": form, "emergency": emergency})


@role_required(*EDIT_ROLES)
def impact_edit(request, pk):
    emergency = _editable_emergency(request.user, pk)
    form = ImpactForm(
        request.POST or None, instance=Impact.objects.filter(emergency=emergency).first()
    )
    if request.method == "POST" and form.is_valid():
        try:
            save_impact(emergency, request.user, form.cleaned_data)
        except WorkflowError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "The impact was saved.")
        return redirect("emergencies:emergency_detail", pk=emergency.pk)
    return render(request, "emergencies/impact_form.html", {"form": form, "emergency": emergency})


@require_POST
@role_required(*EDIT_ROLES)
def status_change(request, pk):
    emergency = get_object_or_404(visible_emergencies(request.user), pk=pk)
    status = request.POST.get("status", "")
    if status not in allowed_statuses(request.user, emergency):
        raise PermissionDenied
    try:
        change_status(emergency, status, request.user, request.POST.get("note", "").strip())
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"The status is now {LABELS[status]}.")
    return redirect("emergencies:emergency_detail", pk=emergency.pk)


@require_POST
@role_required(*EDIT_ROLES)
def note_add(request, pk):
    emergency = _editable_emergency(request.user, pk)
    try:
        add_note(emergency, request.user, request.POST.get("note", ""))
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The note was added.")
    return redirect("emergencies:emergency_detail", pk=emergency.pk)
