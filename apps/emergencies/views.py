from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import role_required
from apps.accounts.roles import ADMINISTRATOR, RISK_MANAGER

from .forms import EmergencyTypeForm
from .models import EmergencyType


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
