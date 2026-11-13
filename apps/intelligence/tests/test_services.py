import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from apps.emergencies.models import Emergency, EmergencyType
from apps.intelligence import services
from apps.intelligence.models import (
    IMPACT,
    MUNICIPAL_RISK,
    PROFILES,
    SIMILARITY,
    ModelVersion,
    Prediction,
)
from apps.intelligence.training import activate_version, save_version, train_component
from apps.places.models import Department, Municipality
from ml.tests.conftest import make_synthetic_frame

ALL_COMPONENTS = (IMPACT, PROFILES, SIMILARITY, MUNICIPAL_RISK)


@pytest.fixture(autouse=True)
def fresh_cache():
    services.clear_cache()
    yield
    services.clear_cache()


@pytest.fixture(scope="module")
def trained():
    frame = make_synthetic_frame()
    return {component: train_component(component, frame, {}) for component in ALL_COMPONENTS}


def make_version(trained, component, metadata=None):
    if metadata is None and component == IMPACT:
        metadata = {"type_counts": {"Flood": 200, "Wildfire": 200, "Landslide": 200}}
    version = save_version(component, trained[component], None, metadata)
    activate_version(version)
    return version


def activate_models(trained, components=ALL_COMPONENTS):
    return {component: make_version(trained, component) for component in components}


@pytest.fixture
def emergency(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    flood, _ = EmergencyType.objects.get_or_create(name="Flood")
    return Emergency.objects.create(
        emergency_type=flood,
        municipality=municipality,
        occurred_at=timezone.now() - timedelta(hours=1),
        status="reported",
    )


def test_predict_on_save_stores_versioned_predictions(db, trained, emergency):
    versions = activate_models(trained, (IMPACT, MUNICIPAL_RISK))
    services.predict_on_save(emergency)
    impact = Prediction.objects.get(component=IMPACT)
    risk = Prediction.objects.get(component=MUNICIPAL_RISK)
    assert Prediction.objects.count() == 2
    assert impact.model_version == versions[IMPACT]
    assert risk.model_version == versions[MUNICIPAL_RISK]
    assert 0 <= impact.score <= 1
    assert impact.output["probability"] == impact.score
    assert isinstance(impact.output["is_high_impact"], bool)
    assert impact.output["kind"] in {"logistic_regression", "gradient_boosting"}
    assert all(set(f) == {"feature", "value", "weight"} for f in impact.output["factors"])
    assert set(risk.output) == {"level", "k"}
    assert risk.output["level"] is not None


def test_no_active_model_stores_nothing(db, emergency):
    services.predict_on_save(emergency)
    services.predict_profile(emergency)
    assert services.suggest_similar(emergency) is None
    assert services.active_model(IMPACT) is None
    assert not Prediction.objects.exists()


def test_unreadable_artifact_is_unavailable(db, trained, emergency, caplog):
    version = make_version(trained, IMPACT)
    ModelVersion.objects.filter(pk=version.pk).update(artifact=b"broken")
    with caplog.at_level("ERROR"):
        services.predict_on_save(emergency)
    assert not Prediction.objects.filter(component=IMPACT).exists()
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_impact_failure_does_not_stop_risk(db, trained, emergency, monkeypatch):
    activate_models(trained, (IMPACT, MUNICIPAL_RISK))

    def boom(self, frame):
        raise RuntimeError("boom")

    monkeypatch.setattr("ml.impact.ImpactModel.probability", boom)
    services.predict_on_save(emergency)
    assert list(Prediction.objects.values_list("component", flat=True)) == [MUNICIPAL_RISK]


def test_rare_type_gets_no_impact_prediction(db, trained, emergency):
    make_version(trained, IMPACT, {"type_counts": {"Flood": 2}})
    make_version(trained, MUNICIPAL_RISK)
    services.predict_on_save(emergency)
    assert not Prediction.objects.filter(component=IMPACT).exists()
    assert Prediction.objects.filter(component=MUNICIPAL_RISK).exists()


def test_user_municipality_gets_estimate_and_insufficient_history(db, trained, emergency):
    activate_models(trained, (IMPACT, MUNICIPAL_RISK))
    emergency.municipality = Municipality.objects.create(
        department=emergency.municipality.department, name="NEW TOWN"
    )
    emergency.save()
    services.predict_on_save(emergency)
    assert Prediction.objects.filter(component=IMPACT).exists()
    assert Prediction.objects.get(component=MUNICIPAL_RISK).output["level"] is None


def test_cache_reloads_after_activation(db, trained, emergency):
    make_version(trained, MUNICIPAL_RISK)
    services.predict_on_save(emergency)
    second = make_version(trained, MUNICIPAL_RISK)
    services.predict_on_save(emergency)
    assert services.latest_predictions(emergency)[MUNICIPAL_RISK].model_version == second
    assert Prediction.objects.count() == 2


def test_active_model_is_cached_between_calls(db, trained, django_assert_num_queries):
    make_version(trained, MUNICIPAL_RISK)
    first = services.active_model(MUNICIPAL_RISK)
    with django_assert_num_queries(1):
        assert services.active_model(MUNICIPAL_RISK)[1] is first[1]


def test_profile_prediction_is_stored(db, trained, emergency):
    make_version(trained, PROFILES)
    services.predict_profile(emergency)
    assert isinstance(Prediction.objects.get(component=PROFILES).output["profile"], str)


def test_suggest_similar_stores_neighbors_and_actions(db, trained, emergency):
    make_version(trained, SIMILARITY)
    prediction = services.suggest_similar(emergency)
    assert prediction is not None and prediction.component == SIMILARITY
    assert prediction.output["neighbors"]
    assert set(prediction.output["neighbors"][0]) == {
        "reference",
        "distance",
        "event_type",
        "occurred_on",
    }
    assert prediction.output["suggested_actions"]
    assert Prediction.objects.count() == 1


def test_latest_predictions_returns_newest_per_component(db, trained, emergency):
    make_version(trained, PROFILES)
    services.predict_profile(emergency)
    services.predict_profile(emergency)
    latest = services.latest_predictions(emergency)
    assert set(latest) == {PROFILES}
    assert latest[PROFILES].pk == Prediction.objects.order_by("-pk").first().pk


@pytest.mark.parametrize("module", ["apps.intelligence.services", "apps.emergencies.views"])
def test_importing_does_not_load_pandas_or_sklearn(module):
    script = (
        "import os, sys, django\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
        "django.setup()\n"
        f"import {module}\n"
        "loaded = [name for name in ('pandas', 'sklearn') if name in sys.modules]\n"
        "sys.exit(','.join(loaded) or 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
