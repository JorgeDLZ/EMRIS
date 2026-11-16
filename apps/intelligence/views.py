import logging
import threading

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import connections
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import role_required
from apps.accounts.roles import CAPABILITIES
from apps.intelligence.models import (
    COMPONENT_CHOICES,
    IMPACT,
    MUNICIPAL_RISK,
    PROFILES,
    SIMILARITY,
    ModelVersion,
    MonitoringCheck,
    Prediction,
    TrainingRun,
)
from apps.intelligence.monitoring import MonitoringUnavailable, run_check
from apps.intelligence.training import (
    RetrainInProgress,
    activate_version,
    execute_runs,
    expire_stale_runs,
    start_runs,
)

logger = logging.getLogger(__name__)

RECENT_RUNS = 20
RECENT_CHECKS = 10
NOT_AVAILABLE = "—"
NO_SCORE_REFERENCE = "Not available until the next retrain"
SCORE_STEP = 5
PREDICTION_PAGE_SIZE = 50
COMPONENT_LABELS = dict(COMPONENT_CHOICES)


def run_in_thread(runs):
    try:
        execute_runs(runs)
    except Exception:
        logger.exception("Background training crashed")
    finally:
        connections.close_all()


def scalar_metrics(metrics):
    return {
        name: round(value, 3) if isinstance(value, float) else value
        for name, value in metrics.items()
        if not isinstance(value, (dict, list))
    }


def component_sections():
    versions = ModelVersion.objects.defer("artifact").order_by("component", "-version")
    by_component = {}
    for version in versions:
        by_component.setdefault(version.component, []).append(version)
    sections = []
    for component, label in COMPONENT_CHOICES:
        items = by_component.get(component, [])
        active = next((version for version in items if version.is_active), None)
        score_percent = max(0, min(100, round(active.score * 100))) if active else 0
        sections.append(
            {
                "label": label,
                "active": active,
                "score_step": SCORE_STEP * round(score_percent / SCORE_STEP),
                "metrics": scalar_metrics(active.metrics) if active else {},
                "versions": items,
            }
        )
    return sections


def _drift(indicators, key):
    value = indicators.get(f"{key}_psi")
    if value is None:
        return NOT_AVAILABLE
    return f"{value:.2f} ({indicators.get(f'{key}_drift')})"


def _percent(value):
    return NOT_AVAILABLE if value is None else f"{value:.1%}"


def monitoring_rows(checks):
    rows = []
    for check in checks:
        indicators = check.indicators
        has_score_reference = bool(check.model_version and check.model_version.metadata.get("score_bins"))
        f1 = indicators.get("f1")
        rows.append(
            {
                "check": check,
                "type_drift": _drift(indicators, "type"),
                "department_drift": _drift(indicators, "department"),
                "score_drift": _drift(indicators, "score") if has_score_reference else NO_SCORE_REFERENCE,
                "unseen": _percent(indicators.get("unseen_share")),
                "f1": NOT_AVAILABLE if f1 is None else f"{f1:.3f}",
            }
        )
    return rows


@role_required(*CAPABILITIES["manage_models"])
def model_list(request):
    expire_stale_runs()
    return render(
        request,
        "intelligence/model_list.html",
        {
            "sections": component_sections(),
            "runs": TrainingRun.objects.all()[:RECENT_RUNS],
            "running": TrainingRun.objects.filter(status=TrainingRun.RUNNING).exists(),
            "monitoring": monitoring_rows(
                MonitoringCheck.objects.select_related("model_version").defer("model_version__artifact")[
                    :RECENT_CHECKS
                ]
            ),
        },
    )


@role_required(*CAPABILITIES["manage_models"])
@require_POST
def retrain(request):
    try:
        runs = start_runs(request.user)
    except RetrainInProgress as error:
        messages.error(request, str(error))
        return redirect("intelligence:model_list")
    if settings.INTELLIGENCE_RUN_IN_BACKGROUND:
        threading.Thread(target=run_in_thread, args=(runs,), daemon=True).start()
    else:
        execute_runs(runs)
    messages.success(request, "Training started.")
    return redirect("intelligence:model_list")


@role_required(*CAPABILITIES["manage_models"])
@require_POST
def activate(request, pk):
    version = get_object_or_404(ModelVersion.objects.defer("artifact"), pk=pk)
    activate_version(version)
    messages.success(request, f"{version} is now active.")
    return redirect("intelligence:model_list")


@role_required(*CAPABILITIES["manage_models"])
@require_POST
def run_monitoring(request):
    simulate = request.POST.get("simulate") == "1"
    try:
        check = run_check(request.user, simulate=simulate)
    except MonitoringUnavailable as error:
        messages.error(request, str(error))
        return redirect("intelligence:model_list")
    prefix = "Simulated monitoring check" if simulate else "Monitoring check"
    messages.success(request, f"{prefix} saved: {check.get_status_display()}.")
    return redirect("intelligence:model_list")


def summarize_prediction(prediction):
    """One readable line for a stored inference result."""
    output = prediction.output or {}
    if prediction.component == IMPACT:
        probability = output.get("probability")
        if probability is None:
            return "Not enough history for this event type"
        label = "high impact" if output.get("is_high_impact") else "not high impact"
        return f"{probability:.0%} \u2014 {label}"
    if prediction.component == PROFILES:
        return output.get("profile", NOT_AVAILABLE)
    if prediction.component == SIMILARITY:
        cases = len(output.get("neighbors", []))
        actions = len(output.get("suggested_actions", []))
        return f"{cases} similar case{'s' if cases != 1 else ''}, {actions} suggested action{'s' if actions != 1 else ''}"
    if prediction.component == MUNICIPAL_RISK:
        level = output.get("level")
        return "Insufficient history" if level is None else f"Risk level {level} of {output.get('k')}"
    return NOT_AVAILABLE


@role_required(*CAPABILITIES["manage_models"])
def prediction_list(request):
    component = request.GET.get("component", "")
    predictions = (
        Prediction.objects.select_related(
            "emergency__emergency_type", "emergency__municipality", "model_version", "requested_by"
        )
        .defer("model_version__artifact")
        .order_by("-created_at", "-pk")
    )
    if component in COMPONENT_LABELS:
        predictions = predictions.filter(component=component)
    else:
        component = ""
    page = Paginator(predictions, PREDICTION_PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [
        {"prediction": prediction, "summary": summarize_prediction(prediction)} for prediction in page
    ]
    return render(
        request,
        "intelligence/prediction_list.html",
        {
            "page": page,
            "rows": rows,
            "component": component,
            "components": COMPONENT_CHOICES,
            "querystring": f"component={component}" if component else "",
        },
    )
