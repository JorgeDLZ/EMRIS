from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.accounts.forms import RegistrationForm
from apps.accounts.roles import get_role


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
