import logging

from .artifacts import load_model
from .frames import emergency_frame, municipality_id
from .models import COMPONENTS, IMPACT, MUNICIPAL_RISK, PROFILES, SIMILARITY, ModelVersion, Prediction

logger = logging.getLogger(__name__)

MIN_TYPE_CASES = 3
NOT_ENOUGH_HISTORY = "not_enough_history"

_cache: dict[str, tuple[ModelVersion, object]] = {}


def clear_cache() -> None:
    _cache.clear()


def active_model(component):
    version = (
        ModelVersion.objects.filter(component=component, is_active=True).defer("artifact").first()
    )
    if version is None:
        _cache.pop(component, None)
        return None
    cached = _cache.get(component)
    if cached is not None and cached[0].pk == version.pk:
        return cached
    try:
        artifact = ModelVersion.objects.values_list("artifact", flat=True).get(pk=version.pk)
        model = load_model(bytes(artifact))
    except Exception:
        logger.exception("The active %s model could not be loaded", component)
        _cache.pop(component, None)
        return None
    _cache[component] = (version, model)
    return version, model


def _store(emergency, version, output, score=None):
    return Prediction.objects.create(
        emergency=emergency,
        model_version=version,
        component=version.component,
        output=output,
        score=score,
    )


def _predict_impact(emergency):
    loaded = active_model(IMPACT)
    if loaded is None:
        return
    version, model = loaded
    type_name = emergency.emergency_type.name
    if version.metadata.get("type_counts", {}).get(type_name, 0) < MIN_TYPE_CASES:
        logger.info("Impact estimate unavailable: too few cases of %s", type_name)
        _store(emergency, version, {"probability": None, "reason": NOT_ENOUGH_HISTORY})
        return
    frame = emergency_frame(emergency)
    probability = float(model.probability(frame)[0])
    output = {
        "kind": model.kind,
        "probability": probability,
        "is_high_impact": bool(model.predict(frame)[0]),
        "factors": [
            {"feature": str(factor.feature), "value": str(factor.value), "weight": float(factor.weight)}
            for factor in model.explain(frame)[0]
        ],
    }
    _store(emergency, version, output, probability)


def _predict_municipal_risk(emergency):
    loaded = active_model(MUNICIPAL_RISK)
    if loaded is None:
        return
    version, model = loaded
    level = model.level_of(municipality_id(emergency.municipality))
    output = {"level": None if level is None else int(level), "k": int(model.k)}
    _store(emergency, version, output)


def predict_on_save(emergency) -> None:
    for predict in (_predict_impact, _predict_municipal_risk):
        try:
            predict(emergency)
        except Exception:
            logger.exception("%s failed for emergency %s", predict.__name__, emergency.pk)


def predict_profile(emergency) -> None:
    try:
        loaded = active_model(PROFILES)
        if loaded is None:
            return
        version, model = loaded
        profile = model.assign(emergency_frame(emergency))[0]
        _store(emergency, version, {"profile": str(profile)})
    except Exception:
        logger.exception("Profile prediction failed for emergency %s", emergency.pk)


def suggest_similar(emergency):
    try:
        from ml.similarity import suggest_actions

        loaded = active_model(SIMILARITY)
        if loaded is None:
            return None
        version, model = loaded
        neighbors = model.neighbors(emergency_frame(emergency))[0]
        output = {
            "neighbors": [
                {
                    "reference": neighbor.reference,
                    "distance": float(neighbor.distance),
                    "event_type": neighbor.event_type,
                    "occurred_on": neighbor.occurred_on.isoformat(),
                }
                for neighbor in neighbors
            ],
            "suggested_actions": [str(code) for code in suggest_actions(neighbors)],
        }
        return _store(emergency, version, output)
    except Exception:
        logger.exception("Similar emergencies failed for emergency %s", emergency.pk)
        return None


def latest_predictions(emergency) -> dict[str, Prediction]:
    latest = {}
    for component in COMPONENTS:
        prediction = (
            Prediction.objects.filter(emergency=emergency, component=component)
            .select_related("model_version")
            .defer("model_version__artifact")
            .order_by("-created_at", "-pk")
            .first()
        )
        if prediction is not None:
            latest[component] = prediction
    return latest
