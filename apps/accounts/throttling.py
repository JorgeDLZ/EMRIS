from datetime import timedelta
from ipaddress import ip_address

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import LoginAttempt

WINDOW = timedelta(minutes=15)
MAX_FAILURES_PER_USER_IP = 5
MAX_FAILURES_PER_IP = 20
USERNAME_MAX_LENGTH = 150
LOCKED_MESSAGE = "Too many failed attempts. Try again in 15 minutes."


def client_ip(request) -> str:
    header = settings.CLIENT_IP_HEADER
    if header:
        try:
            return str(ip_address(request.headers.get(header, "").strip()))
        except ValueError:
            pass
    return request.META.get("REMOTE_ADDR", "")


def _key(username: str) -> str:
    return username.lower()[:USERNAME_MAX_LENGTH]


def _recent_failures(ip: str):
    return LoginAttempt.objects.filter(ip_address=ip, attempted_at__gte=timezone.now() - WINDOW)


def is_locked(username: str, ip: str) -> bool:
    recent = _recent_failures(ip)
    if recent.count() >= MAX_FAILURES_PER_IP:
        return True
    return recent.filter(username=_key(username)).count() >= MAX_FAILURES_PER_USER_IP


def record_failure(username: str, ip: str) -> None:
    LoginAttempt.objects.filter(attempted_at__lt=timezone.now() - WINDOW).delete()
    LoginAttempt.objects.create(username=_key(username), ip_address=ip)


def clear_failures(username: str, ip: str) -> None:
    LoginAttempt.objects.filter(username=_key(username), ip_address=ip).delete()
