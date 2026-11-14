from types import SimpleNamespace

from django.db import OperationalError
from django.http import HttpResponse
from django.urls import path


def raise_operational_error(request):
    raise OperationalError("database is unavailable")


def ok(request):
    return HttpResponse("ok")


urlpatterns = [
    path("boom/", raise_operational_error),
    path("ok/", ok),
    path("", ok, name="home"),
]


def test_health_ok(client, db):
    r = client.get("/health/")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_health_db_down(client, monkeypatch):
    def failing_cursor():
        raise OperationalError("database is unavailable")

    monkeypatch.setattr("config.views.connection", SimpleNamespace(cursor=failing_cursor))
    r = client.get("/health/")
    assert r.status_code == 503 and r.json() == {"status": "unavailable"}


def test_operational_error_renders_503_page(client, settings):
    settings.ROOT_URLCONF = __name__
    r = client.get("/boom/")
    assert r.status_code == 503
    assert "temporarily unavailable" in r.content.decode()
    assert client.get("/ok/").status_code == 200
