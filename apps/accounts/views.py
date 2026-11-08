from django.contrib.auth import login
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.forms import RegistrationForm, UserRoleForm
from apps.accounts.models import User
from apps.accounts.permissions import role_required
from apps.accounts.roles import ADMINISTRATOR, get_role
from apps.accounts.services import RoleChangeError, set_role


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("accounts:pending")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def pending(request):
    if get_role(request.user) is not None:
        return redirect("home")
    return render(request, "accounts/pending.html")


@role_required(ADMINISTRATOR)
def user_list(request):
    users = User.objects.order_by("username")
    return render(request, "accounts/user_list.html", {"users": users})


@role_required(ADMINISTRATOR)
def user_role(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = UserRoleForm(request.POST or None, initial={"role": get_role(target) or ""})
    if request.method == "POST" and form.is_valid():
        try:
            set_role(request.user, target, form.cleaned_data["role"] or None)
        except RoleChangeError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, f"Role updated for {target.username}.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_role.html", {"form": form, "target": target})
