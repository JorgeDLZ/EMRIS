from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import role_required
from apps.accounts.roles import ALL_ROLES, EDIT_ROLES, MANAGE_ROLES
from apps.emergencies.policies import (
    can_approve_plan,
    can_edit_plan,
    can_start_plan,
    can_update_action,
    visible_emergencies,
)
from apps.emergencies.workflow import WorkflowError

from .forms import ActionForm, AssignmentForm, ResourceForm
from .models import DONE, Action, Resource, ResourceAssignment
from .services import (
    add_action,
    advance_action,
    approve_plan,
    assign_resource,
    assigned_quantity,
    remove_assignment,
    start_plan,
    update_action,
)


def _visible_emergency(user, pk):
    return get_object_or_404(
        visible_emergencies(user).select_related("emergency_type", "municipality__department"),
        pk=pk,
    )


def _existing_plan(emergency):
    plan = getattr(emergency, "action_plan", None)
    if plan is None:
        raise Http404
    return plan


def _visible_action(user, pk):
    action = get_object_or_404(Action.objects.select_related("plan__emergency"), pk=pk)
    _visible_emergency(user, action.plan.emergency_id)
    return action


def _visible_assignment(user, pk):
    assignment = get_object_or_404(
        ResourceAssignment.objects.select_related("plan__emergency", "resource"), pk=pk
    )
    _visible_emergency(user, assignment.plan.emergency_id)
    return assignment


def _detail_context(user, emergency, plan, assignment_form=None):
    context = {
        "emergency": emergency,
        "plan": plan,
        "can_start": can_start_plan(user, emergency),
    }
    if plan is not None:
        context.update(
            {
                "rows": [
                    (action, can_update_action(user, action) and action.status != DONE)
                    for action in plan.actions.select_related("owner")
                ],
                "assignments": plan.assignments.select_related("resource"),
                "can_edit": can_edit_plan(user, plan),
                "can_approve": can_approve_plan(user, plan) and not plan.is_approved,
                "assignment_form": assignment_form or AssignmentForm(),
            }
        )
    return context


@role_required(*ALL_ROLES)
def plan_detail(request, emergency_pk):
    emergency = _visible_emergency(request.user, emergency_pk)
    plan = getattr(emergency, "action_plan", None)
    return render(request, "plans/plan_detail.html", _detail_context(request.user, emergency, plan))


@require_POST
@role_required(*EDIT_ROLES)
def plan_start(request, emergency_pk):
    emergency = _visible_emergency(request.user, emergency_pk)
    if not can_start_plan(request.user, emergency):
        raise PermissionDenied
    try:
        start_plan(emergency, request.user)
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The action plan was started.")
    return redirect("plans:plan_detail", emergency_pk=emergency.pk)


@require_POST
@role_required(*MANAGE_ROLES)
def plan_approve(request, emergency_pk):
    emergency = _visible_emergency(request.user, emergency_pk)
    plan = _existing_plan(emergency)
    if not can_approve_plan(request.user, plan):
        raise PermissionDenied
    try:
        approve_plan(plan, request.user)
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The action plan was approved.")
    return redirect("plans:plan_detail", emergency_pk=emergency.pk)


@role_required(*EDIT_ROLES)
def action_create(request, emergency_pk):
    emergency = _visible_emergency(request.user, emergency_pk)
    plan = _existing_plan(emergency)
    if not can_edit_plan(request.user, plan):
        raise PermissionDenied
    form = ActionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            add_action(plan, **form.cleaned_data)
        except WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The action was added.")
            return redirect("plans:plan_detail", emergency_pk=emergency.pk)
    return render(
        request, "plans/action_form.html", {"form": form, "emergency": emergency, "action": None}
    )


@role_required(*EDIT_ROLES)
def action_edit(request, pk):
    action = _visible_action(request.user, pk)
    emergency = action.plan.emergency
    if not can_edit_plan(request.user, action.plan):
        raise PermissionDenied
    form = ActionForm(request.POST or None, instance=action)
    if request.method == "POST" and form.is_valid():
        try:
            update_action(action, **form.cleaned_data)
        except WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The action was updated.")
            return redirect("plans:plan_detail", emergency_pk=emergency.pk)
    return render(
        request, "plans/action_form.html", {"form": form, "emergency": emergency, "action": action}
    )


@require_POST
@role_required(*ALL_ROLES)
def action_advance(request, pk):
    action = _visible_action(request.user, pk)
    if not can_update_action(request.user, action):
        raise PermissionDenied
    try:
        advance_action(action, request.POST.get("expected_status") or None)
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The action was advanced.")
    return redirect("plans:plan_detail", emergency_pk=action.plan.emergency_id)


@require_POST
@role_required(*EDIT_ROLES)
def assignment_create(request, emergency_pk):
    emergency = _visible_emergency(request.user, emergency_pk)
    plan = _existing_plan(emergency)
    if not can_edit_plan(request.user, plan):
        raise PermissionDenied
    form = AssignmentForm(request.POST)
    if form.is_valid():
        try:
            assign_resource(plan, form.cleaned_data["resource"], form.cleaned_data["quantity"])
        except WorkflowError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The resource was assigned.")
            return redirect("plans:plan_detail", emergency_pk=emergency.pk)
    return render(
        request,
        "plans/plan_detail.html",
        _detail_context(request.user, emergency, plan, assignment_form=form),
    )


@require_POST
@role_required(*EDIT_ROLES)
def assignment_remove(request, pk):
    assignment = _visible_assignment(request.user, pk)
    if not can_edit_plan(request.user, assignment.plan):
        raise PermissionDenied
    try:
        remove_assignment(assignment)
    except WorkflowError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The assignment was removed.")
    return redirect("plans:plan_detail", emergency_pk=assignment.plan.emergency_id)


@role_required(*MANAGE_ROLES)
def resource_list(request):
    rows = []
    for resource in Resource.objects.all():
        assigned = assigned_quantity(resource)
        stock = resource.quantity_available
        rows.append((resource, max(stock - assigned, 0), max(assigned - stock, 0)))
    return render(request, "plans/resource_list.html", {"rows": rows})


@role_required(*MANAGE_ROLES)
def resource_create(request):
    form = ResourceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        resource = form.save()
        messages.success(request, f"{resource.name} was added.")
        return redirect("plans:resource_list")
    return render(request, "plans/resource_form.html", {"form": form, "resource": None})


@role_required(*MANAGE_ROLES)
def resource_edit(request, pk):
    resource = get_object_or_404(Resource, pk=pk)
    form = ResourceForm(request.POST or None, instance=resource)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{resource.name} was updated.")
        assigned = assigned_quantity(resource)
        if assigned > resource.quantity_available:
            messages.warning(
                request,
                f"{assigned} are assigned to open emergencies; the stock is now below that.",
            )
        return redirect("plans:resource_list")
    return render(request, "plans/resource_form.html", {"form": form, "resource": resource})
