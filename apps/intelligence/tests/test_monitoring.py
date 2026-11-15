import logging
from datetime import datetime, timedelta
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.emergencies.models import Emergency, EmergencyType
from apps.intelligence import monitoring, services, training
from apps.intelligence.models import IMPACT, ModelVersion, MonitoringCheck, Prediction
from apps.intelligence.monitoring import MonitoringUnavailable, run_check
from apps.intelligence.training import train_initial
from apps.places.models import Department, Municipality
from ml.tests.conftest import make_synthetic_frame

NEW_METADATA = ("score_bins", "department_counts", "municipalities", "flagged_share")


@pytest.fixture(autouse=True)
def fresh_cache():
    services.clear_cache()
    yield
    services.clear_cache()


@pytest.fixture
def trained(db, monkeypatch):
    frame = make_synthetic_frame()
    monkeypatch.setattr(training, "build_training_frame", lambda: frame)
    monkeypatch.setattr(training, "seismic_inputs", lambda: {})
    monkeypatch.setattr(monitoring, "build_training_frame", lambda: frame)
    train_initial()
    return frame


def impact_version():
    return ModelVersion.objects.get(component=IMPACT, is_active=True)


def make_emergencies(count, unavailable=0):
    department, _ = Department.objects.get_or_create(code="05", defaults={"name": "ANTIOQUIA"})
    municipality, _ = Municipality.objects.get_or_create(
        code="05001", defaults={"department": department, "name": "MEDELLÍN"}
    )
    flood, _ = EmergencyType.objects.get_or_create(name="Flood")
    version = impact_version()
    occurred_at = timezone.make_aware(datetime(2026, 2, 1, 12))
    for index in range(count):
        emergency = Emergency.objects.create(
            emergency_type=flood, municipality=municipality, occurred_at=occurred_at, status="reported"
        )
        score = None if index < unavailable else 0.4
        Prediction.objects.create(
            emergency=emergency, model_version=version, component=IMPACT,
            output={"probability": score}, score=score,
        )


def test_new_impact_versions_store_score_bins(trained):
    metadata = impact_version().metadata
    assert set(metadata["score_bins"]) == {str(index) for index in range(10)}
    assert sum(metadata["score_bins"].values()) == len(trained)
    assert set(NEW_METADATA) <= set(metadata)
    assert 0.0 <= metadata["flagged_share"] <= 1.0


def test_check_without_new_emergencies_is_not_enough_data(trained):
    check = run_check()
    assert check.status == "not_enough_data"
    assert check.indicators["emergencies"] == 0
    assert check.is_simulated is False
    assert check.model_version == impact_version()


def test_check_on_a_version_without_score_bins(trained):
    version = impact_version()
    for key in NEW_METADATA:
        version.metadata.pop(key)
    version.save(update_fields=["metadata"])
    make_emergencies(35)
    check = run_check()
    for key in ("score_psi", "department_psi", "unseen_share", "reference_flagged_share"):
        assert check.indicators[key] is None
    assert check.indicators["type_psi"] is not None


def test_operational_check_reads_window_predictions(trained):
    make_emergencies(35, unavailable=5)
    check = run_check()
    assert check.indicators["emergencies"] == 35
    assert check.indicators["unavailable_share"] == round(5 / 35, 4)
    assert check.window_start.isoformat() == "2026-01-01"


def test_simulated_check_is_labelled_and_writes_no_emergencies(trained, caplog):
    emergencies, predictions = Emergency.objects.count(), Prediction.objects.count()
    with caplog.at_level(logging.INFO, logger="apps.intelligence.monitoring"):
        check = run_check(simulate=True)
    assert check.is_simulated is True
    assert Emergency.objects.count() == emergencies
    assert Prediction.objects.count() == predictions
    assert check.indicators["emergencies"] == 300
    assert check.window_end - check.window_start == timedelta(days=89)
    messages = [r.getMessage() for r in caplog.records if r.name == "apps.intelligence.monitoring"]
    assert messages and messages[0].startswith("[SIMULATED] ")
    assert str(check).startswith("Monitoring check ")


def test_check_without_active_model_raises(db):
    with pytest.raises(MonitoringUnavailable, match="No active impact model."):
        run_check()
    assert MonitoringCheck.objects.count() == 0


def test_monitor_models_command(trained):
    out = StringIO()
    call_command("monitor_models", "--simulate", stdout=out)
    output = out.getvalue()
    assert output.startswith("Simulated data")
    assert "type_psi:" in output


def test_monitor_models_command_without_models(db):
    with pytest.raises(CommandError, match="No active impact model."):
        call_command("monitor_models", stdout=StringIO())
