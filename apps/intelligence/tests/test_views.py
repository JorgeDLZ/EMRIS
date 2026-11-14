import pytest
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.intelligence import views
from apps.intelligence.models import ModelVersion, TrainingRun
from apps.intelligence.tests.test_training import synthetic  # noqa: F401
from apps.intelligence.training import train_initial


@pytest.fixture(autouse=True)
def synchronous(settings):
    settings.INTELLIGENCE_RUN_IN_BACKGROUND = False


def login(client, role):
    user = User.objects.create_user(f"user-{role}", password="pass-12345")
    user.groups.add(Group.objects.get(name=role))
    client.force_login(user)
    return user


def messages_of(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


def test_page_is_administrator_only(client, db):
    for role in (RISK_MANAGER, OPERATOR, ACTION_OWNER):
        login(client, role)
        assert client.get(reverse("intelligence:model_list")).status_code == 403
    login(client, ADMINISTRATOR)
    response = client.get(reverse("intelligence:model_list"))
    assert response.status_code == 200
    assert response.content.decode().count("No active model") == 4


def test_superuser_can_open_the_page(client, db):
    client.force_login(User.objects.create_superuser("root", password="pass-12345"))
    assert client.get(reverse("intelligence:model_list")).status_code == 200


def test_page_lists_versions_and_runs(client, db, synthetic):
    train_initial()
    login(client, ADMINISTRATOR)
    content = client.get(reverse("intelligence:model_list")).content.decode()
    assert "Active: Impact estimator v1" in content
    assert "Impact estimator" in content
    assert "Municipal risk" in content
    assert "No active model" not in content
    assert '<button type="submit">Retrain</button>' in content
    assert "disabled" not in content


def test_retrain_runs_and_redirects(client, db, synthetic):
    train_initial()
    login(client, ADMINISTRATOR)
    response = client.post(reverse("intelligence:retrain"))
    assert response.status_code == 302
    assert response.url == reverse("intelligence:model_list")
    assert TrainingRun.objects.filter(status=TrainingRun.SUCCEEDED).count() == 4
    assert messages_of(response) == ["Training started."]


def test_retrain_twice_is_refused(client, db, synthetic):
    login(client, ADMINISTRATOR)
    TrainingRun.objects.create(component="impact")
    response = client.post(reverse("intelligence:retrain"))
    assert messages_of(response) == ["A training run is already in progress."]
    assert TrainingRun.objects.count() == 1
    page = client.get(reverse("intelligence:model_list")).content.decode()
    assert '<button type="submit" disabled>Retrain</button>' in page


def test_rollback_activates_earlier_version(client, db, synthetic):
    train_initial()
    first = ModelVersion.objects.get(component="impact")
    newer = ModelVersion.objects.create(
        component="impact",
        version=2,
        artifact=bytes(first.artifact),
        primary_metric="f1",
        score=0.5,
        metrics={},
        trained_on={},
        library_versions={},
    )
    views.activate_version(newer)
    login(client, ADMINISTRATOR)
    response = client.post(reverse("intelligence:activate", args=[first.pk]))
    assert response.url == reverse("intelligence:model_list")
    assert messages_of(response) == ["Impact estimator v1 is now active."]
    first.refresh_from_db()
    newer.refresh_from_db()
    assert first.is_active and not newer.is_active


def test_activate_unknown_version_is_404(client, db):
    login(client, ADMINISTRATOR)
    assert client.post(reverse("intelligence:activate", args=[999])).status_code == 404


def test_post_only_and_role_checks(client, db, synthetic):
    train_initial()
    version = ModelVersion.objects.first()
    active_before = set(ModelVersion.objects.filter(is_active=True).values_list("pk", flat=True))
    login(client, ADMINISTRATOR)
    assert client.get(reverse("intelligence:retrain")).status_code == 405
    assert client.get(reverse("intelligence:activate", args=[version.pk])).status_code == 405
    for role in (RISK_MANAGER, OPERATOR, ACTION_OWNER):
        login(client, role)
        assert client.post(reverse("intelligence:retrain")).status_code == 403
        assert client.post(reverse("intelligence:activate", args=[version.pk])).status_code == 403
    assert TrainingRun.objects.count() == 0
    assert ModelVersion.objects.get(pk=version.pk).is_active == version.is_active
    assert set(ModelVersion.objects.filter(is_active=True).values_list("pk", flat=True)) == active_before


def test_background_mode_starts_a_thread(client, db, monkeypatch, settings):
    settings.INTELLIGENCE_RUN_IN_BACKGROUND = True
    started = []

    class FakeThread:
        def __init__(self, target, args, daemon):
            started.append((target, args, daemon))

        def start(self):
            started.append("started")

    monkeypatch.setattr(views.threading, "Thread", FakeThread)
    login(client, ADMINISTRATOR)
    response = client.post(reverse("intelligence:retrain"))
    assert messages_of(response) == ["Training started."]
    (target, args, daemon), marker = started
    assert target is views.run_in_thread
    assert daemon is True and marker == "started"
    assert len(args[0]) == 4


def test_run_in_thread_executes_and_closes_connections(monkeypatch):
    calls = []
    monkeypatch.setattr(views, "execute_runs", lambda runs: calls.append(("execute", runs)))
    monkeypatch.setattr(views.connections, "close_all", lambda: calls.append("closed"))
    views.run_in_thread(["run"])
    assert calls == [("execute", ["run"]), "closed"]


def test_run_in_thread_logs_unexpected_errors(monkeypatch, caplog):
    def explode(runs):
        raise RuntimeError("boom")

    monkeypatch.setattr(views, "execute_runs", explode)
    monkeypatch.setattr(views.connections, "close_all", lambda: None)
    views.run_in_thread([])
    assert "Background training crashed" in caplog.text


def test_navigation_link_is_for_administrators(client, db):
    login(client, ADMINISTRATOR)
    assert reverse("intelligence:model_list") in client.get(reverse("dashboard:index")).content.decode()
    login(client, OPERATOR)
    assert reverse("intelligence:model_list") not in client.get(reverse("dashboard:index")).content.decode()


def test_key_metrics_show_text_and_rounded_floats(client, db, synthetic):
    train_initial()
    active = ModelVersion.objects.get(component="impact", is_active=True)
    login(client, ADMINISTRATOR)
    content = client.get(reverse("intelligence:model_list")).content.decode()
    assert f"model: {active.metrics['model']}" in content
    assert f"f1: {round(active.metrics['f1'], 3)}" in content
