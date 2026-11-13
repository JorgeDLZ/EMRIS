import logging
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from apps.intelligence.artifacts import dump_model, library_versions, load_model
from apps.intelligence.frames import build_training_frame, seismic_inputs
from apps.intelligence.models import (
    COMPONENTS,
    IMPACT,
    MUNICIPAL_RISK,
    PROFILES,
    SIMILARITY,
    ModelVersion,
    TrainingRun,
)

logger = logging.getLogger(__name__)

RUN_TIMEOUT = timedelta(minutes=30)
GATE_MIN_ROWS = 50
TRAINING_WORKING_MEMORY_MB = 64
TIES_ACTIVATE = {SIMILARITY, MUNICIPAL_RISK}

NO_ACTIVE_MODEL = "No active model"
BETTER = "Better than the active model"
NOT_BETTER = "Not better than the active model"
NOT_ENOUGH_DATA = "Not enough new data to compare"
ACTIVE_CHANGED = "Active model changed during training"


class RetrainInProgress(Exception):
    def __init__(self, message="A training run is already in progress."):
        super().__init__(message)


@dataclass(frozen=True)
class GateDecision:
    activate: bool
    candidate_score: float
    active_score: float | None
    reason: str


@contextmanager
def _bounded_training_memory():
    from sklearn import config_context

    with config_context(working_memory=TRAINING_WORKING_MEMORY_MB):
        yield


def train_component(component, frame, seismic):
    if component == IMPACT:
        from ml.impact import train_impact

        return train_impact(frame)
    if component == PROFILES:
        from ml.profiles import train_profiles

        return train_profiles(frame)
    if component == SIMILARITY:
        from ml.similarity import train_similarity

        return train_similarity(frame)
    from ml.municipal_risk import train_municipal_risk

    return train_municipal_risk(frame, seismic)


def _load_active(active):
    if active is None:
        return None
    try:
        return load_model(bytes(active.artifact))
    except Exception:
        logger.warning("Active %s artifact could not be loaded", active.component, exc_info=True)
        return None


def _compare(component, candidate_score, active_score):
    ties = component in TIES_ACTIVATE
    better = candidate_score > active_score or (ties and candidate_score == active_score)
    return GateDecision(better, candidate_score, active_score, BETTER if better else NOT_BETTER)


def _impact_gate(candidate, active, active_model, frame):
    import pandas as pd

    from ml.evaluation import classification_metrics

    fresh = frame[pd.to_datetime(frame["occurred_on"]) > pd.Timestamp(active.trained_on["end"])]
    labels = fresh["is_high_impact"].to_numpy(dtype=bool)
    if len(fresh) < GATE_MIN_ROWS or not labels.any():
        return GateDecision(False, candidate.score, None, NOT_ENOUGH_DATA)
    active_score = classification_metrics(
        labels, active_model.probability(fresh), active_model.threshold
    )["f1"]
    return _compare(IMPACT, candidate.score, active_score)


def _risk_gate(candidate, active_model, frame, seismic):
    from ml.municipal_risk import evaluate_municipal_risk

    common = set(candidate.model.levels) & set(active_model.levels)
    if not common:
        return GateDecision(False, candidate.score, None, NOT_ENOUGH_DATA)

    def silhouette(model):
        restricted = replace(
            model, levels={code: level for code, level in model.levels.items() if code in common}
        )
        return evaluate_municipal_risk(restricted, frame, seismic)["silhouette"]

    return _compare(MUNICIPAL_RISK, silhouette(candidate.model), silhouette(active_model))


def gate(component, candidate, active, frame, seismic):
    active_model = _load_active(active)
    if active_model is None:
        return GateDecision(True, candidate.score, None, NO_ACTIVE_MODEL)
    if component == IMPACT:
        return _impact_gate(candidate, active, active_model, frame)
    if component == PROFILES:
        from ml.profiles import evaluate_profiles

        return _compare(
            PROFILES,
            evaluate_profiles(candidate.model, frame)["silhouette"],
            evaluate_profiles(active_model, frame)["silhouette"],
        )
    if component == SIMILARITY:
        from ml.similarity import evaluate_similarity

        metric = candidate.primary_metric
        return _compare(
            SIMILARITY,
            evaluate_similarity(candidate.model, frame)[metric],
            evaluate_similarity(active_model, frame)[metric],
        )
    return _risk_gate(candidate, active_model, frame, seismic)


def save_version(component, result, actor, metadata=None):
    latest = (
        ModelVersion.objects.filter(component=component)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    return ModelVersion.objects.create(
        component=component,
        version=(latest or 0) + 1,
        artifact=dump_model(result.model),
        primary_metric=result.primary_metric,
        score=result.score,
        metrics=result.metrics,
        trained_on=result.trained_on,
        metadata=metadata or {},
        library_versions=library_versions(),
        created_by=actor,
    )


@transaction.atomic
def activate_version(version):
    list(ModelVersion.objects.select_for_update().filter(component=version.component))
    ModelVersion.objects.filter(component=version.component, is_active=True).update(is_active=False)
    ModelVersion.objects.filter(pk=version.pk).update(is_active=True)
    version.is_active = True


def expire_stale_runs(now=None):
    cutoff = (now or timezone.now()) - RUN_TIMEOUT
    return TrainingRun.objects.filter(status=TrainingRun.RUNNING, started_at__lt=cutoff).update(
        status=TrainingRun.FAILED, message="Timed out", finished_at=timezone.now()
    )


def start_runs(actor):
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    f"LOCK TABLE {TrainingRun._meta.db_table} IN SHARE ROW EXCLUSIVE MODE"
                )
        expire_stale_runs()
        if TrainingRun.objects.filter(status=TrainingRun.RUNNING).exists():
            raise RetrainInProgress()
        return [
            TrainingRun.objects.create(component=component, triggered_by=actor)
            for component in COMPONENTS
        ]


def _metadata(component, frame):
    if component != IMPACT:
        return {}
    counts = frame["event_type"].value_counts()
    return {"type_counts": {str(name): int(count) for name, count in counts.items()}}


def _message(version, decision):
    verb = "activated" if decision.activate else "kept inactive"
    if decision.active_score is None:
        return f"v{version.version} {verb}: {decision.reason}"
    scores = f"{decision.candidate_score:.3f} vs {decision.active_score:.3f}"
    if decision.activate:
        return f"v{version.version} {verb}: {scores}"
    return f"v{version.version} {verb}: {decision.reason} ({scores})"


def _finish(run, status, message, version=None, activated=False):
    applied = TrainingRun.objects.filter(pk=run.pk, status=TrainingRun.RUNNING).update(
        status=status,
        message=message,
        candidate_version=version,
        activated=activated,
        finished_at=timezone.now(),
    )
    return applied > 0


def _begin(run):
    return (
        TrainingRun.objects.filter(pk=run.pk, status=TrainingRun.RUNNING).update(
            started_at=timezone.now()
        )
        > 0
    )


def _execute(run, frame, seismic):
    component = run.component
    if not _begin(run):
        return
    active_id = (
        ModelVersion.objects.filter(component=component, is_active=True)
        .values_list("pk", flat=True)
        .first()
    )
    active = ModelVersion.objects.filter(pk=active_id).first() if active_id else None
    result = train_component(component, frame, seismic)
    decision = gate(component, result, active, frame, seismic)
    with transaction.atomic():
        current = TrainingRun.objects.select_for_update().get(pk=run.pk)
        if current.status != TrainingRun.RUNNING:
            return
        list(ModelVersion.objects.select_for_update().filter(component=component))
        current_id = (
            ModelVersion.objects.filter(component=component, is_active=True)
            .values_list("pk", flat=True)
            .first()
        )
        if current_id != active_id:
            decision = GateDecision(False, result.score, None, ACTIVE_CHANGED)
        version = save_version(component, result, run.triggered_by, _metadata(component, frame))
        if decision.activate:
            activate_version(version)
        _finish(run, TrainingRun.SUCCEEDED, _message(version, decision), version, decision.activate)


def execute_runs(runs):
    with _bounded_training_memory():
        try:
            frame = build_training_frame()
            seismic = seismic_inputs()
        except Exception as exc:
            logger.exception("Training inputs could not be built")
            for run in runs:
                _finish(run, TrainingRun.FAILED, str(exc))
            return
        for run in runs:
            try:
                _execute(run, frame, seismic)
            except Exception as exc:
                logger.exception("Training %s failed", run.component)
                _finish(run, TrainingRun.FAILED, str(exc))


def train_initial(actor=None):
    if ModelVersion.objects.exists():
        raise ValueError("Models already exist; use retrain.")
    with _bounded_training_memory():
        frame = build_training_frame()
        seismic = seismic_inputs()
        versions = []
        with transaction.atomic():
            for component in COMPONENTS:
                result = train_component(component, frame, seismic)
                version = save_version(component, result, actor, _metadata(component, frame))
                activate_version(version)
                versions.append(version)
        return versions
