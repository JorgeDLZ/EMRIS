import pytest
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.intelligence import monitoring, services, views
from apps.intelligence.models import IMPACT, ModelVersion, MonitoringCheck, TrainingRun
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
    assert '<button type="submit" class="btn btn-primary">Retrain</button>' in content
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
    assert '<button type="submit" class="btn btn-primary" disabled>Retrain</button>' in page


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


def test_score_bar_step_is_clamped(db):
    for component, score in (("impact", 0.734), ("profiles", -0.05)):
        ModelVersion.objects.create(
            component=component, version=1, artifact=b"", primary_metric="score", score=score,
            metrics={}, trained_on={}, library_versions={}, is_active=True,
        )
    steps = {section["label"]: section["score_step"] for section in views.component_sections()}
    assert steps["Impact estimator"] == 75
    assert steps["Emergency profiles"] == 0
    assert steps["Municipal risk"] == 0


@pytest.fixture
def monitored(monkeypatch, synthetic):
    monkeypatch.setattr(monitoring, "build_training_frame", lambda: synthetic)
    services.clear_cache()
    train_initial()
    yield synthetic
    services.clear_cache()


def monitoring_section(content):
    return content[content.index("<h2>Monitoring</h2>") : content.index("<h2>Recent training runs</h2>")]


def test_admin_runs_a_simulated_check(client, db, monitored):
    login(client, ADMINISTRATOR)
    response = client.post(reverse("intelligence:run_monitoring"), {"simulate": "1"})
    assert response.status_code == 302
    assert response.url == reverse("intelligence:model_list")
    check = MonitoringCheck.objects.get()
    assert check.is_simulated is True
    assert any(m.startswith("Simulated monitoring check saved: ") for m in messages_of(response))


def test_admin_runs_an_operational_check(client, db, monitored):
    login(client, ADMINISTRATOR)
    response = client.post(reverse("intelligence:run_monitoring"))
    assert MonitoringCheck.objects.get().is_simulated is False
    assert "Monitoring check saved: Not enough data." in messages_of(response)


def test_monitoring_without_an_active_model(client, db):
    login(client, ADMINISTRATOR)
    response = client.post(reverse("intelligence:run_monitoring"))
    assert response.status_code == 302
    assert "No active impact model." in messages_of(response)
    assert MonitoringCheck.objects.count() == 0


def test_models_page_lists_checks_with_simulated_label(client, db, monitored):
    login(client, ADMINISTRATOR)
    client.post(reverse("intelligence:run_monitoring"))
    client.post(reverse("intelligence:run_monitoring"), {"simulate": "1"})
    version = ModelVersion.objects.get(component=IMPACT, is_active=True)
    version.metadata.pop("score_bins")
    version.save(update_fields=["metadata"])
    section = monitoring_section(client.get(reverse("intelligence:model_list")).content.decode())
    assert '<button type="submit" class="btn btn-secondary">Run check</button>' in section
    assert "Run simulated check</button>" in section
    assert '<span class="badge badge-warning">Simulated</span>' in section
    assert "Operational" in section
    assert "—" in section
    assert "Not available until the next retrain" in section
    assert "Event-type distribution drifted" in section


def test_models_page_shows_the_ten_latest_checks(client, db, monitored):
    login(client, ADMINISTRATOR)
    client.post(reverse("intelligence:run_monitoring"))
    check = MonitoringCheck.objects.get()
    for _ in range(11):
        check.pk = None
        check.save()
    section = monitoring_section(client.get(reverse("intelligence:model_list")).content.decode())
    assert section.count("<tr>") - 1 == views.RECENT_CHECKS == 10


def test_monitoring_requires_post_and_administrator(client, db):
    login(client, ADMINISTRATOR)
    assert client.get(reverse("intelligence:run_monitoring")).status_code == 405
    for role in (RISK_MANAGER, OPERATOR, ACTION_OWNER):
        login(client, role)
        assert client.post(reverse("intelligence:run_monitoring"), {"simulate": "1"}).status_code == 403
    assert MonitoringCheck.objects.count() == 0


def test_inference_history_is_administrator_only(client, db):
    for role in (RISK_MANAGER, OPERATOR, ACTION_OWNER):
        login(client, role)
        assert client.get(reverse("intelligence:prediction_list")).status_code == 403
    login(client, ADMINISTRATOR)
    response = client.get(reverse("intelligence:prediction_list"))
    assert response.status_code == 200
    assert "No predictions have been stored yet" in response.content.decode()


def test_inference_history_lists_user_version_result_and_time(client, db, synthetic):
    from datetime import timedelta

    from django.utils import timezone

    from apps.emergencies.models import Emergency, EmergencyType
    from apps.intelligence.models import Prediction
    from apps.places.models import Department, Municipality

    admin = login(client, ADMINISTRATOR)
    train_initial()
    version = ModelVersion.objects.get(component=IMPACT, is_active=True)
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    flood, _ = EmergencyType.objects.get_or_create(name="Flood")
    emergency = Emergency.objects.create(
        emergency_type=flood, municipality=municipality, occurred_at=timezone.now() - timedelta(hours=1)
    )
    Prediction.objects.create(
        emergency=emergency,
        model_version=version,
        component=IMPACT,
        output={"probability": 0.31, "is_high_impact": False},
        score=0.31,
        requested_by=admin,
        duration_ms=12.34,
    )
    content = client.get(reverse("intelligence:prediction_list"), {"component": IMPACT}).content.decode()
    assert "31% \u2014 not high impact" in content
    assert f"v{version.version}" in content
    assert admin.username in content
    assert "12.3" in content


def test_summaries_cover_every_component():
    from apps.intelligence.models import MUNICIPAL_RISK, PROFILES, SIMILARITY, Prediction

    def summary(component, output):
        return views.summarize_prediction(Prediction(component=component, output=output))

    assert summary(IMPACT, {"probability": None}) == "Not enough history for this event type"
    assert summary(IMPACT, {"probability": 0.84, "is_high_impact": True}) == "84% \u2014 high impact"
    assert summary(PROFILES, {"profile": "Injuries and deaths"}) == "Injuries and deaths"
    assert summary(SIMILARITY, {"neighbors": [{}] * 5, "suggested_actions": ["a"]}) == "5 similar cases, 1 suggested action"
    assert summary(MUNICIPAL_RISK, {"level": 2, "k": 3}) == "Risk level 2 of 3"
    assert summary(MUNICIPAL_RISK, {"level": None, "k": 3}) == "Insufficient history"
