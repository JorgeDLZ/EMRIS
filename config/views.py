from django.db import OperationalError, connection
from django.http import JsonResponse
from django.shortcuts import render


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def home(request):
    user = request.user
    signed_in = user.is_authenticated
    has_access = signed_in and bool(user.role_label or user.is_superuser)
    return render(
        request,
        "home.html",
        {"show_dashboard_link": has_access, "awaiting_role": signed_in and not has_access},
    )
