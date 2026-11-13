from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import role_required
from apps.accounts.roles import ADMINISTRATOR, OPERATOR, RISK_MANAGER
from ml.text import normalize_name

from .forms import MunicipalityForm
from .models import Department, Municipality
from .services import (
    DuplicateMunicipality,
    approve_municipality,
    find_similar,
    register_municipality,
    reject_municipality,
)

PAGE_SIZE = 50


@role_required(ADMINISTRATOR, RISK_MANAGER, OPERATOR)
def municipality_list(request):
    municipalities = Municipality.objects.visible_to(request.user).select_related("department")

    department = request.GET.get("department", "")
    if department.isascii() and department.isdigit() and len(department) <= 9:
        municipalities = municipalities.filter(department_id=int(department))
    else:
        department = ""

    query = request.GET.get("q", "").replace("\x00", "").strip()
    if query:
        municipalities = municipalities.filter(name_key__icontains=normalize_name(query))

    page = Paginator(municipalities, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "places/municipality_list.html",
        {
            "page": page,
            "departments": Department.objects.order_by("name"),
            "department": department,
            "query": query,
        },
    )


@role_required(ADMINISTRATOR, RISK_MANAGER, OPERATOR)
def municipality_create(request):
    form = MunicipalityForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        department = form.cleaned_data["department"]
        name = form.cleaned_data["name"]
        similar = find_similar(
            department, name, queryset=Municipality.objects.visible_to(request.user)
        )
        key = normalize_name(name)
        is_exact = any(match.name_key == key for match in similar)
        if similar and not is_exact and not form.cleaned_data["confirm_new"]:
            return render(request, "places/municipality_form.html", {"form": form, "similar": similar})
        try:
            municipality = register_municipality(department, name, request.user)
        except DuplicateMunicipality:
            form.add_error("name", f"{name} already exists in {department.name}.")
        else:
            if municipality.validation == Municipality.PENDING:
                messages.success(request, f"{municipality.name} was registered and awaits validation.")
            else:
                messages.success(request, f"{municipality.name} was registered.")
            return redirect("places:municipality_list")
    return render(request, "places/municipality_form.html", {"form": form, "similar": []})


@role_required(ADMINISTRATOR, RISK_MANAGER)
def municipality_pending(request):
    pending = Municipality.objects.filter(validation=Municipality.PENDING).select_related(
        "department", "created_by"
    )
    return render(request, "places/municipality_pending.html", {"municipalities": pending})


@require_POST
@role_required(ADMINISTRATOR, RISK_MANAGER)
def municipality_approve(request, pk):
    municipality = get_object_or_404(Municipality, pk=pk)
    if municipality.validation == Municipality.PENDING:
        approve_municipality(municipality)
        messages.success(request, f"{municipality.name} was approved.")
    else:
        messages.error(request, f"{municipality.name} is not pending validation.")
    return redirect("places:municipality_pending")


@require_POST
@role_required(ADMINISTRATOR, RISK_MANAGER)
def municipality_reject(request, pk):
    municipality = get_object_or_404(Municipality, pk=pk)
    try:
        reject_municipality(municipality)
    except ValueError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"{municipality.name} was rejected.")
    return redirect("places:municipality_pending")
