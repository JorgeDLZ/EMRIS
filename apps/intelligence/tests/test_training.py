from datetime import timedelta

import pandas as pd

import pytest
from django.utils import timezone

from apps.intelligence import training
from apps.intelligence.artifacts import load_model
from apps.intelligence.models import COMPONENTS, ModelVersion, TrainingRun
from apps.intelligence.training import (
    RetrainInProgress,
    activate_version,
    execute_runs,
    expire_stale_runs,
    start_runs,
    train_initial,
)
from ml.evaluation import classification_metrics
from ml.tests.conftest import make_synthetic_frame


@pytest.fixture
def synthetic(monkeypatch):
    frame = make_synthetic_frame()
    monkeypatch.setattr(training, "build_training_frame", lambda: frame)
    monkeypatch.setattr(training, "seismic_inputs", lambda: {})
    return frame


def active(component):
    return ModelVersion.objects.get(component=component, is_active=True)


def retrain():
    runs = start_runs(None)
    execute_runs(runs)
    return {run.component: run for run in TrainingRun.objects.filter(pk__in=[r.pk for r in runs])}


def test_train_initial_activates_all_four(db, synthetic):
    versions = train_initial()
    assert [version.component for version in versions] == list(COMPONENTS)
    assert all(version.version == 1 and version.is_active for version in versions)
    assert ModelVersion.objects.filter(is_active=True).count() == 4
    impact = active("impact")
    assert set(impact.library_versions) == {"scikit-learn", "pandas", "numpy"}
    assert impact.metadata["type_counts"] == {"Flood": 200, "Landslide": 200, "Wildfire": 200}
    assert impact.trained_on["rows"] == 600


def test_train_initial_refuses_when_versions_exist(db, synthetic):
    train_initial()
    with pytest.raises(ValueError, match="Models already exist; use retrain."):
        train_initial()


def test_retrain_without_new_data_keeps_impact_and_profiles(db, synthetic):
    train_initial()
    runs = retrain()
    assert active("impact").version == 1
    assert active("profiles").version == 1
    assert runs["impact"].message.endswith("Not enough new data to compare")
    assert runs["impact"].status == TrainingRun.SUCCEEDED
    assert not runs["impact"].activated
    assert runs["impact"].candidate_version.version == 2
    assert runs["impact"].finished_at is not None


def test_similarity_tie_activates_candidate(db, synthetic, monkeypatch):
    train_initial()
    monkeypatch.setattr("ml.similarity.evaluate_similarity", lambda model, frame: {"precision_at_5": 0.5})
    runs = retrain()
    assert active("similarity").version == 2
    assert runs["similarity"].activated
    assert runs["similarity"].message == "v2 activated: 0.500 vs 0.500"


def test_worse_candidate_is_kept_inactive(db, synthetic, monkeypatch):
    import ml.profiles

    train_initial()
    real_train = ml.profiles.train_profiles
    candidates = []

    def train(frame):
        result = real_train(frame)
        candidates.append(result.model)
        return result

    def evaluate(model, frame):
        return {"silhouette": 0.1 if model is candidates[-1] else 0.9}

    monkeypatch.setattr("ml.profiles.train_profiles", train)
    monkeypatch.setattr("ml.profiles.evaluate_profiles", evaluate)
    runs = retrain()
    assert active("profiles").version == 1
    assert runs["profiles"].status == TrainingRun.SUCCEEDED
    assert not runs["profiles"].activated
    assert runs["profiles"].message.startswith("v2 kept inactive: Not better than the active model")
    assert ModelVersion.objects.filter(component="profiles", version=2, is_active=False).exists()


def test_better_candidate_is_activated(db, synthetic, monkeypatch):
    import ml.profiles

    train_initial()
    real_train = ml.profiles.train_profiles
    candidates = []

    def train(frame):
        result = real_train(frame)
        candidates.append(result.model)
        return result

    monkeypatch.setattr("ml.profiles.train_profiles", train)
    monkeypatch.setattr(
        "ml.profiles.evaluate_profiles",
        lambda model, frame: {"silhouette": 0.9 if model is candidates[-1] else 0.1},
    )
    runs = retrain()
    assert active("profiles").version == 2
    assert runs["profiles"].activated
    assert runs["profiles"].message == "v2 activated: 0.900 vs 0.100"


def test_failure_is_recorded_and_others_continue(db, synthetic, monkeypatch):
    train_initial()

    def fail(frame):
        raise RuntimeError("clustering failed")

    monkeypatch.setattr("ml.profiles.train_profiles", fail)
    runs = retrain()
    assert runs["profiles"].status == TrainingRun.FAILED
    assert runs["profiles"].message == "clustering failed"
    assert runs["profiles"].finished_at is not None
    assert {runs[c].status for c in COMPONENTS if c != "profiles"} == {TrainingRun.SUCCEEDED}
    assert active("profiles").version == 1


def test_start_creates_one_running_run_per_component(db, synthetic):
    runs = start_runs(None)
    assert [run.component for run in runs] == list(COMPONENTS)
    assert {run.status for run in runs} == {TrainingRun.RUNNING}


def test_second_start_is_refused(db, synthetic):
    start_runs(None)
    with pytest.raises(RetrainInProgress, match="A training run is already in progress."):
        start_runs(None)


def test_stale_runs_expire(db, synthetic):
    stale = start_runs(None)
    TrainingRun.objects.filter(pk__in=[run.pk for run in stale]).update(
        started_at=timezone.now() - timedelta(minutes=31)
    )
    assert expire_stale_runs() == 4
    run = TrainingRun.objects.get(pk=stale[0].pk)
    assert run.status == TrainingRun.FAILED
    assert run.message == "Timed out"
    assert run.finished_at is not None
    assert len(start_runs(None)) == 4


def test_activate_version_rolls_back(db, synthetic, monkeypatch):
    train_initial()
    monkeypatch.setattr("ml.similarity.evaluate_similarity", lambda model, frame: {"precision_at_5": 0.5})
    retrain()
    assert active("similarity").version == 2
    activate_version(ModelVersion.objects.get(component="similarity", version=1))
    assert active("similarity").version == 1
    assert not ModelVersion.objects.get(component="similarity", version=2).is_active


def test_unloadable_active_artifact_counts_as_no_active_model(db, synthetic):
    train_initial()
    ModelVersion.objects.filter(component="profiles", is_active=True).update(artifact=b"broken")
    runs = retrain()
    assert runs["profiles"].activated
    assert runs["profiles"].message == "v2 activated: No active model"
    assert active("profiles").version == 2


def extended_frame(frame, rows=150):
    fresh = frame.tail(rows).copy()
    fresh["reference"] = "later:" + fresh["reference"]
    fresh["occurred_on"] = fresh["occurred_on"] + timedelta(days=366)
    return pd.concat([frame, fresh], ignore_index=True)


def active_f1_on_new_rows(frame):
    version = active("impact")
    model = load_model(bytes(version.artifact))
    fresh = frame[pd.to_datetime(frame["occurred_on"]) > pd.Timestamp(version.trained_on["end"])]
    labels = fresh["is_high_impact"].to_numpy(dtype=bool)
    assert len(fresh) >= training.GATE_MIN_ROWS and labels.any()
    return classification_metrics(labels, model.probability(fresh), model.threshold)["f1"]


def force_impact_score(monkeypatch, score):
    import ml.impact

    real = ml.impact.train_impact

    def train(frame):
        result = real(frame)
        result.metrics["f1"] = score
        return result

    monkeypatch.setattr("ml.impact.train_impact", train)


def test_impact_gate_activates_a_better_candidate(db, synthetic, monkeypatch):
    train_initial()
    frame = extended_frame(synthetic)
    monkeypatch.setattr(training, "build_training_frame", lambda: frame)
    active_f1 = active_f1_on_new_rows(frame)
    force_impact_score(monkeypatch, active_f1 + 0.01)
    run = retrain()["impact"]
    assert active("impact").version == 2
    assert run.activated
    assert run.message == f"v2 activated: {active_f1 + 0.01:.3f} vs {active_f1:.3f}"


def test_impact_gate_keeps_active_on_equal_score(db, synthetic, monkeypatch):
    train_initial()
    frame = extended_frame(synthetic)
    monkeypatch.setattr(training, "build_training_frame", lambda: frame)
    active_f1 = active_f1_on_new_rows(frame)
    force_impact_score(monkeypatch, active_f1)
    run = retrain()["impact"]
    assert active("impact").version == 1
    assert not run.activated
    assert run.message.startswith("v2 kept inactive: Not better than the active model")


def test_municipal_risk_gate_scores_both_models_on_common_codes(db, synthetic, monkeypatch):
    train_initial()
    remapped = synthetic.assign(
        municipality=synthetic["municipality"].replace({"68002": "99002", "68003": "99003"})
    )
    monkeypatch.setattr(training, "build_training_frame", lambda: remapped)
    seen = []

    def evaluate(model, frame, seismic):
        seen.append(set(model.levels))
        return {"silhouette": 0.5}

    monkeypatch.setattr("ml.municipal_risk.evaluate_municipal_risk", evaluate)
    run = retrain()["municipal_risk"]
    common = set(synthetic["municipality"].unique()) - {"68002", "68003"}
    assert seen == [common, common]
    assert run.activated


def test_run_expired_while_executing_is_not_overwritten(db, synthetic, monkeypatch):
    import ml.profiles

    real = ml.profiles.train_profiles

    def train(frame):
        TrainingRun.objects.filter(component="profiles").update(
            started_at=timezone.now() - timedelta(minutes=31)
        )
        expire_stale_runs()
        return real(frame)

    monkeypatch.setattr("ml.profiles.train_profiles", train)
    run = retrain()["profiles"]
    assert run.status == TrainingRun.FAILED
    assert run.message == "Timed out"
    assert not ModelVersion.objects.filter(component="profiles").exists()


def test_run_expired_while_queued_is_skipped(db, synthetic):
    runs = start_runs(None)
    TrainingRun.objects.filter(pk=runs[0].pk).update(
        started_at=timezone.now() - timedelta(minutes=31)
    )
    expire_stale_runs()
    execute_runs(runs)
    first = TrainingRun.objects.get(pk=runs[0].pk)
    assert first.status == TrainingRun.FAILED
    assert first.message == "Timed out"
    assert not ModelVersion.objects.filter(component=first.component).exists()
    assert ModelVersion.objects.count() == 3


def test_each_run_starts_its_clock_when_it_begins(db, synthetic):
    runs = start_runs(None)
    old = timezone.now() - timedelta(minutes=29)
    TrainingRun.objects.filter(pk__in=[run.pk for run in runs]).update(started_at=old)
    execute_runs(runs)
    assert all(run.started_at > old for run in TrainingRun.objects.filter(pk__in=[r.pk for r in runs]))


def test_candidate_stays_inactive_when_active_changed_during_training(db, synthetic, monkeypatch):
    import ml.similarity

    train_initial()
    monkeypatch.setattr("ml.similarity.evaluate_similarity", lambda model, frame: {"precision_at_5": 0.5})
    real = ml.similarity.train_similarity

    def train(frame):
        result = real(frame)
        replacement = ModelVersion.objects.get(component="similarity", version=1)
        replacement.pk = None
        replacement.version = 2
        replacement.is_active = False
        replacement.save()
        activate_version(replacement)
        return result

    monkeypatch.setattr("ml.similarity.train_similarity", train)
    run = retrain()["similarity"]
    assert run.message == "v3 kept inactive: Active model changed during training"
    assert active("similarity").version == 2
    assert not run.activated
