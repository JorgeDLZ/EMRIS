from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.intelligence.models import ModelVersion, TrainingRun
from apps.intelligence.tests.test_training import synthetic  # noqa: F401
from apps.intelligence.training import start_runs


def run_command(name):
    out = StringIO()
    call_command(name, stdout=out)
    return out.getvalue().splitlines()


def test_train_initial_prints_and_activates(db, synthetic):
    lines = run_command("train_initial")
    assert len(lines) == 4
    assert lines[0].startswith("Impact estimator v1: f1 ")
    assert all(line.split(": ", 1)[1].split(" ")[1].count(".") == 1 for line in lines)
    assert ModelVersion.objects.filter(is_active=True).count() == 4


def test_train_initial_refuses_twice(db, synthetic):
    run_command("train_initial")
    with pytest.raises(CommandError, match="Models already exist; use retrain."):
        run_command("train_initial")


def test_retrain_prints_each_run(db, synthetic):
    run_command("train_initial")
    lines = run_command("retrain")
    assert len(lines) == 4
    assert lines[0] == "Impact estimator: Succeeded — v2 kept inactive: Not enough new data to compare"
    assert TrainingRun.objects.filter(status=TrainingRun.RUNNING).count() == 0


def test_retrain_refused_while_running(db, synthetic):
    start_runs(None)
    with pytest.raises(CommandError, match="A training run is already in progress."):
        run_command("retrain")


def test_retrain_fails_when_a_run_fails(db, synthetic, monkeypatch):
    run_command("train_initial")

    def fail(frame):
        raise RuntimeError("clustering failed")

    monkeypatch.setattr("ml.profiles.train_profiles", fail)
    out = StringIO()
    with pytest.raises(CommandError, match="Emergency profiles"):
        call_command("retrain", stdout=out)
    assert len(out.getvalue().splitlines()) == 4
