import logging
from datetime import date, timedelta

from django.utils import timezone

from apps.emergencies.models import CLOSED, Emergency

from .frames import build_training_frame, municipality_id
from .models import IMPACT, MonitoringCheck, Prediction
from .services import active_model

logger = logging.getLogger(__name__)

NO_ACTIVE_MODEL = "No active impact model."
REFERENCE_KEYS = ("type_counts", "department_counts", "municipalities", "flagged_share", "score_bins")
WINDOW_COLUMNS = ["reference", "event_type", "department", "municipality", "is_high_impact"]


class MonitoringUnavailable(Exception):
    def __init__(self, message=NO_ACTIVE_MODEL):
        super().__init__(message)


def _reference(version):
    reference = {key: version.metadata.get(key) for key in REFERENCE_KEYS}
    reference["reference_f1"] = version.metrics.get("f1")
    return reference


def _latest_scores(emergencies):
    scores = {}
    predictions = Prediction.objects.filter(component=IMPACT, emergency__in=emergencies).order_by(
        "emergency_id", "-created_at", "-pk"
    )
    for emergency_id, score in predictions.values_list("emergency_id", "score"):
        scores.setdefault(emergency_id, score)
    return scores


def _real_labels(emergency_ids):
    if not emergency_ids:
        return {}
    training = build_training_frame()
    wanted = {f"emergency:{pk}" for pk in emergency_ids}
    rows = training[training["reference"].isin(wanted)]
    return dict(zip(rows["reference"], rows["is_high_impact"].astype(bool)))


def _operational_inputs(start, end):
    import numpy as np
    import pandas as pd

    emergencies = list(
        Emergency.objects.filter(occurred_at__date__gte=start, occurred_at__date__lte=end)
        .select_related("emergency_type", "municipality__department", "impact")
        .order_by("occurred_at", "pk")
    )
    closed_with_impact = [
        emergency.pk
        for emergency in emergencies
        if emergency.status == CLOSED and getattr(emergency, "impact", None) is not None
    ]
    labels = _real_labels(closed_with_impact)
    scores = _latest_scores(emergencies)
    frame = pd.DataFrame(
        [
            {
                "reference": f"emergency:{emergency.pk}",
                "event_type": emergency.emergency_type.name,
                "department": emergency.municipality.department.code,
                "municipality": municipality_id(emergency.municipality),
                "is_high_impact": labels.get(f"emergency:{emergency.pk}", False),
            }
            for emergency in emergencies
        ],
        columns=WINDOW_COLUMNS,
    )
    score_values = np.array(
        [np.nan if scores.get(emergency.pk) is None else scores[emergency.pk] for emergency in emergencies],
        dtype=float,
    )
    labelled = frame["reference"].isin(set(labels)).to_numpy(dtype=bool)
    return frame, score_values, labelled


def _simulated_inputs(version, model, start):
    import numpy as np

    from ml.monitoring import simulate_operational_frame

    ranked = sorted(version.metadata.get("type_counts", {}).items(), key=lambda item: -item[1])
    shifted_type = ranked[1][0] if len(ranked) > 1 else None
    frame = simulate_operational_frame(build_training_frame(), start, shifted_type=shifted_type)
    return frame, model.probability(frame), np.ones(len(frame), dtype=bool)


def run_check(actor=None, simulate=False):
    from ml.monitoring import SIMULATED_DAYS, assess, compute_indicators

    loaded = active_model(IMPACT)
    if loaded is None:
        raise MonitoringUnavailable()
    version, model = loaded
    start = date.fromisoformat(version.trained_on["end"]) + timedelta(days=1)
    if simulate:
        end = start + timedelta(days=SIMULATED_DAYS - 1)
        frame, scores, labelled = _simulated_inputs(version, model, start)
    else:
        end = timezone.localdate()
        frame, scores, labelled = _operational_inputs(start, end)
    indicators = compute_indicators(_reference(version), frame, scores, model.threshold, labelled)
    check = MonitoringCheck.objects.create(
        model_version=version,
        is_simulated=simulate,
        window_start=start,
        window_end=end,
        status=assess(indicators),
        indicators=indicators,
        triggered_by=actor,
    )
    logger.info(
        "%sMonitoring check %s: %s", "[SIMULATED] " if simulate else "", check.pk, check.get_status_display()
    )
    return check
