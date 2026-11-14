from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Case, F, IntegerField, OuterRef, Subquery, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import role_required
from apps.accounts.roles import CAPABILITIES
from apps.intelligence.models import IMPACT, MUNICIPAL_RISK, PROFILES, Prediction
from apps.intelligence.services import latest_predictions, predict_on_save, predict_profile
from apps.plans.models import DONE
from apps.seismic.services import clear_link, confirm_link, suggest_link
from ml.text import normalize_name

from .forms import EmergencyForm, EmergencyTypeForm, ImpactForm
from .models import CLOSED, STATUS_CHOICES, Emergency, EmergencyType, Impact
from .policies import (
    allowed_statuses,
    can_edit_emergency,
    can_edit_plan,
    can_set_status,
    can_start_plan,
    can_update_action,
    visible_emergencies,
)
from .workflow import LABELS, WorkflowError, add_note, change_status, create_emergency, save_impact

PAGE_SIZE = 25
MAX_LOGISTIC_FACTORS = 3


def _impact_factors(output):
    factors = [factor for factor in output.get("factors", []) if factor["weight"] != 0]
    if output.get("kind") == "logistic_regression":
        factors.sort(key=lambda factor: abs(factor["weight"]), reverse=True)
        return [
            {**factor, "raises": factor["weight"] > 0} for factor in factors[:MAX_LOGISTIC_FACTORS]
        ]
    factors = [factor for factor in factors if factor["weight"] > 0]
    factors.sort(key=lambda factor: factor["weight"], reverse=True)
    return factors


def _intelligence_panel(emergency, has_impact):
    predictions = latest_predictions(emergency)
    panel = {"has_impact": has_impact}
    impact = predictions.get(IMPACT)
    if impact is not None and impact.output["probability"] is None:
        panel["impact_reason"] = impact.output["reason"]
    elif impact is not None:
        panel["impact"] = {
            "percent": round(impact.output["probability"] * 100),
            "is_high_impact": impact.output["is_high_impact"],
            "factors": _impact_factors(impact.output),
            "is_directional": impact.output.get("kind") == "logistic_regression",
            "version": impact.model_version,
        }
    profile = predictions.get(PROFILES)
    if profile is not None:
        panel["profile"] = {"name": profile.output["profile"], "version": profile.model_version}
    risk = predictions.get(MUNICIPAL_RISK)
    if risk is not None:
        panel["risk"] = {
            "level": risk.output["level"],
            "k": risk.output["k"],
            "version": risk.model_version,
        }
    return panel


def _to_minute(moment):
    return moment.replace(second=0, microsecond=0)


def _editable_emergency(user, pk):
    emergency = get_object_or_404(
        visible_emergencies(user).select_related("emergency_type", "municipality__department"),
        pk=pk,
    )
    if not can_edit_emergency(user, emergency):
        raise PermissionDenied
    return emergency


@role_required(*CAPABILITIES["manage_catalogs"])
def type_list(request):
    return render(request, "emergencies/type_list.html", {"types": EmergencyType.objects.all()})


@role_required(*CAPABILITIES["manage_catalogs"])
def type_create(request):
    form = EmergencyTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        emergency_type = form.save()
        messages.success(request, f"{emergency_type.name} was added.")
        return redirect("emergencies:type_list")
    return render(request, "emergencies/type_form.html", {"form": form, "emergency_type": None})


@role_required(*CAPABILITIES["manage_catalogs"])
def type_edit(request, pk):
    emergency_type = get_object_or_404(EmergencyType, pk=pk)
    form = EmergencyTypeForm(request.POST or None, instance=emergency_type)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{emergency_type.name} was updated.")
        return redirect("emergencies:type_list")
    return render(request, "emergencies/type_form.html", {"form": form, "emergency_type": emergency_type})


@role_required(*CAPABILITIES["view_emergencies"])
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
    if type_id.isascii() and type_id.isdigit() and len(type_id) <= 9:
        emergencies = emergencies.filter(emergency_type_id=int(type_id))
    else:
        type_id = ""

    query = request.GET.get("q", "").replace("\x00", "").strip()
    if query:
        emergencies = emergencies.filter(municipality__name_key__icontains=normalize_name(query))

    latest_score = (
        Prediction.objects.filter(emergency=OuterRef("pk"), component=IMPACT)
        .order_by("-created_at", "-pk")
        .values("score")[:1]
    )
    emergencies = emergencies.annotate(
        priority=Subquery(latest_score),
        closed_rank=Case(
            When(status=CLOSED, then=Value(1)), default=Value(0), output_field=IntegerField()
        ),
    ).order_by("closed_rank", F("priority").desc(nulls_last=True), "-occurred_at", "-pk")

    page = Paginator(emergencies, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "emergencies/emergency_list.html",
        {
            "page": page,
            "status": status,
            "type_id": type_id,
            "query": query,
            "filtered": bool(status or type_id or query),
            "status_choices": STATUS_CHOICES,
            "types": EmergencyType.objects.all(),
        },
    )


@role_required(*CAPABILITIES["edit_emergencies"])
def emergency_create(request):
    form = EmergencyForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        emergency = create_emergency(request.user, **form.cleaned_data)
        predict_on_save(emergency)
        messages.success(request, "The emergency was reported.")
        return redirect("emergencies:emergency_detail", pk=emergency.pk)
    return render(request, "emergencies/emergency_form.html", {"form": form, "emergency": None})


@role_required(*CAPABILITIES["view_emergencies"])
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
    plan = getattr(emergency, "action_plan", None)
    plan_rows = []
    assignments = []
    if plan is not None:
        plan_rows = [
            (action, can_update_action(user, action) and action.status != DONE)
            for action in plan.actions.select_related("owner")
        ]
        assignments = plan.assignments.select_related("resource")
    impact = Impact.objects.filter(emergency=emergency).first()
    can_edit = can_edit_emergency(user, emergency)
    suggestion = None
    if can_edit and emergency.is_earthquake and emergency.seismic_event is None:
        suggestion = suggest_link(emergency)
    return render(
        request,
        "emergencies/emergency_detail.html",
        {
            "emergency": emergency,
            "suggestion": suggestion,
            "impact": impact,
            "panel": _intelligence_panel(emergency, impact is not None),
            "log": log,
            "plan": plan,
            "plan_rows": plan_rows,
            "assignments": assignments,
            "can_start_plan": can_start_plan(user, emergency),
            "can_edit_plan": plan is not None and can_edit_plan(user, plan),
            "can_edit": can_edit,
            "next_statuses": [(status, LABELS[status]) for status in allowed_statuses(user, emergency)],
        },
    )


@transaction.atomic
def _save_emergency_fields(user, emergency, form):
    locked = Emergency.objects.select_for_update().get(pk=emergency.pk)
    if not can_edit_emergency(user, locked):
        raise PermissionDenied
    fields = EmergencyForm.Meta.fields
    link_changed = (
        locked.emergency_type_id != form.instance.emergency_type_id
        or locked.municipality_id != form.instance.municipality_id
        or _to_minute(locked.occurred_at) != _to_minute(form.instance.occurred_at)
    )
    for name in fields:
        setattr(locked, name, getattr(form.instance, name))
    update_fields = [*fields, "updated_at"]
    if link_changed:
        locked.seismic_event = None
        locked.seismic_link_distance_km = None
        update_fields += ["seismic_event", "seismic_link_distance_km"]
    locked.save(update_fields=update_fields)


@role_required(*CAPABILITIES["edit_emergencies"])
def emergency_edit(request, pk):
    emergency = _editable_emergency(request.user, pk)
    form = EmergencyForm(request.POST or None, instance=emergency, user=request.user)
    if request.method == "POST" and form.is_valid():
        _save_emergency_fields(request.user, emergency, form)
        predict_on_save(
            Emergency.objects.select_related("emergency_type", "municipality__department").get(pk=pk)
        )
        messages.success(request, "The emergency was updated.")
        return redirect("emergencies:emergency_detail", pk=emergency.pk)
    return render(request, "emergencies/emergency_form.html", {"form": form, "emergency": emergency})


@role_required(*CAPABILITIES["edit_emergencies"])
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
            predict_profile(emergency)
            messages.success(request, "The impact was saved.")
        return redirect("emergencies:emergency_detail", pk=emergency.pk)
    return render(request, "emergencies/impact_form.html", {"form": form, "emergency": emergency})


@require_POST
@role_required(*CAPABILITIES["edit_emergencies"])
def status_change(request, pk):
    emergency = get_object_or_404(visible_emergencies(request.user), pk=pk)
    status = request.POST.get("status", "")
    if not can_set_status(request.user, emergency, status):
        raise PermissionDenied
    try:
        change_status(emergency, status, request.user, request.POST.get("note", "").strip())
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"The status is now {LABELS[status]}.")
    return redirect("emergencies:emergency_detail", pk=emergency.pk)


@require_POST
@role_required(*CAPABILITIES["edit_emergencies"])
def note_add(request, pk):
    emergency = _editable_emergency(request.user, pk)
    try:
        add_note(emergency, request.user, request.POST.get("note", ""))
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The note was added.")
    return redirect("emergencies:emergency_detail", pk=emergency.pk)


@require_POST
@role_required(*CAPABILITIES["edit_emergencies"])
def seismic_confirm(request, pk):
    emergency = _editable_emergency(request.user, pk)
    try:
        suggestion = confirm_link(emergency)
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        if suggestion is None:
            messages.error(request, "No SGC event matches; enter magnitude and depth in the form.")
        else:
            messages.success(request, "The SGC event was linked.")
    return redirect("emergencies:emergency_detail", pk=emergency.pk)


@require_POST
@role_required(*CAPABILITIES["edit_emergencies"])
def seismic_clear(request, pk):
    emergency = _editable_emergency(request.user, pk)
    try:
        clear_link(emergency)
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The SGC link was cleared.")
    return redirect("emergencies:emergency_detail", pk=emergency.pk)
