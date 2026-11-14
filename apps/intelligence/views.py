import logging
import threading

from django.conf import settings
from django.contrib import messages
from django.db import connections
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import role_required
from apps.accounts.roles import CAPABILITIES
from apps.intelligence.models import COMPONENT_CHOICES, ModelVersion, TrainingRun
from apps.intelligence.training import (
    RetrainInProgress,
    activate_version,
    execute_runs,
    expire_stale_runs,
    start_runs,
)

logger = logging.getLogger(__name__)

RECENT_RUNS = 20
SCORE_STEP = 5


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
