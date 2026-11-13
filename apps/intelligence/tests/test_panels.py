from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, OPERATOR
from apps.emergencies.models import CLOSED, Impact
from apps.emergencies.tests.test_emergency_views import (  # noqa: F401
    antioquia,
    flood,
    give_action,
    make_emergency,
    make_user,
    medellin,
)
from apps.intelligence.models import IMPACT, MUNICIPAL_RISK, PROFILES, ModelVersion, Prediction


def make_version(component, number=1):
    return ModelVersion.objects.create(
        component=component,
        version=number,
        artifact=b"",
        primary_metric="metric",
        score=0.5,
        metrics={},
        trained_on={},
        library_versions={},
    )


def add_prediction(emergency, component, output, score=None, number=1):
    version = ModelVersion.objects.filter(component=component, version=number).first()
    return Prediction.objects.create(
        emergency=emergency,
        model_version=version or make_version(component, number),
        component=component,
        output=output,
        score=score,
    )


def impact_output(probability, factors=(), kind="logistic_regression"):
    return {
        "kind": kind,
        "probability": probability,
        "is_high_impact": probability >= 0.5,
        "factors": [{"feature": name, "value": value, "weight": weight} for name, value, weight in factors],
    }


def detail(client, emergency, role=OPERATOR):
    user = User.objects.filter(username="ana").first() or make_user("ana", role)
    client.force_login(user)
    return client.get(reverse("emergencies:emergency_detail", args=[emergency.pk]))


def test_panel_shows_predictions_and_versions(client, db, make_emergency):
    emergency = make_emergency()
    Impact.objects.create(emergency=emergency)
    add_prediction(emergency, IMPACT, impact_output(0.63), score=0.63)
    add_prediction(emergency, PROFILES, {"profile": "Flash flood"})
    add_prediction(emergency, MUNICIPAL_RISK, {"level": 2, "k": 3})
    page = detail(client, emergency).content.decode()
    assert "Intelligence" in page
    assert "Estimated high-impact probability: 63 %" in page
    assert "High impact" in page
    assert "Flash flood" in page
    assert "Risk level 2 of 3" in page
    assert "Impact estimator v1" in page
    assert "Emergency profiles v1" in page
    assert "Municipal risk v1" in page


def test_panel_shows_not_high_impact_and_insufficient_history(client, db, make_emergency):
    emergency = make_emergency()
    add_prediction(emergency, IMPACT, impact_output(0.2), score=0.2)
    add_prediction(emergency, MUNICIPAL_RISK, {"level": None, "k": 3})
    page = detail(client, emergency).content.decode()
    assert "Not high impact" in page
    assert "Insufficient history" in page


def test_panel_shows_unavailable_without_predictions(client, db, make_emergency):
    emergency = make_emergency()
    page = detail(client, emergency).content.decode()
    assert "Intelligence" in page
    assert page.count("Prediction unavailable") == 2
    assert "Profile pending" in page
    Impact.objects.create(emergency=emergency)
    page = detail(client, emergency).content.decode()
    assert page.count("Prediction unavailable") == 3
    assert "Profile pending" not in page


def test_factor_display_rules(client, db, make_emergency):
    logistic = make_emergency()
    add_prediction(
        logistic,
        IMPACT,
        impact_output(
            0.6,
            [
                ("Event type", "Flood", 0.9),
                ("Month", "March", 0.0),
                ("Department", "ANTIOQUIA", -0.7),
                ("Hour", "14", 0.4),
                ("Weekday", "Monday", 0.1),
            ],
        ),
        score=0.6,
    )
    page = detail(client, logistic).content.decode()
    assert "Main factors:" in page
    assert "<li>Event type: Flood (raises)</li>" in page
    assert "<li>Department: ANTIOQUIA (lowers)</li>" in page
    assert "<li>Hour: 14 (raises)</li>" in page
    assert "<li>Month: March" not in page
    assert "<li>Weekday: Monday" not in page

    boosting = make_emergency()
    add_prediction(
        boosting,
        IMPACT,
        impact_output(
            0.6,
            [("Event type", "Flood", 0.5), ("Month", "March", 0.0), ("Department", "ANTIOQUIA", -0.2)],
            kind="gradient_boosting",
        ),
        score=0.6,
        number=2,
    )
    page = detail(client, boosting).content.decode()
    assert "Most influential factors in the model:" in page
    assert "Main factors:" not in page
    assert "<li>Event type: Flood</li>" in page
    assert "(raises)" not in page
    assert "(lowers)" not in page
    assert "<li>Month: March" not in page
    assert "<li>Department: ANTIOQUIA" not in page


def test_no_factor_list_when_no_factor_survives(client, db, make_emergency):
    emergency = make_emergency()
    add_prediction(emergency, IMPACT, impact_output(0.6, [("Month", "March", 0.0)]), score=0.6)
    page = detail(client, emergency).content.decode()
    assert "Main factors:" not in page
    assert "Most influential factors in the model:" not in page


def test_list_orders_by_priority(client, db, make_emergency):
    now = timezone.now()
    low = make_emergency(occurred_at=now - timedelta(days=1))
    unknown = make_emergency(occurred_at=now - timedelta(days=2))
    high = make_emergency(occurred_at=now - timedelta(days=3))
    closed = make_emergency(status=CLOSED, occurred_at=now - timedelta(days=4))
    add_prediction(low, IMPACT, impact_output(0.2), score=0.2)
    add_prediction(high, IMPACT, impact_output(0.9), score=0.9)
    add_prediction(closed, IMPACT, impact_output(0.95), score=0.95)
    client.force_login(make_user("ana", OPERATOR))
    response = client.get(reverse("emergencies:emergency_list"))
    assert list(response.context["page"].object_list) == [high, low, unknown, closed]
    page = response.content.decode()
    assert "Priority" in page
    rows = page.split("<tr>")
    row = next(r for r in rows if reverse("emergencies:emergency_detail", args=[unknown.pk]) in r)
    assert "—" in row
    assert "%" not in row
    high_row = next(r for r in rows if reverse("emergencies:emergency_detail", args=[high.pk]) in r)
    assert "90 %" in high_row


def test_list_uses_latest_impact_prediction(client, db, make_emergency):
    older = make_emergency()
    newer = make_emergency()
    add_prediction(older, IMPACT, impact_output(0.1), score=0.1)
    add_prediction(older, IMPACT, impact_output(0.8), score=0.8)
    add_prediction(newer, IMPACT, impact_output(0.5), score=0.5)
    client.force_login(make_user("ana", OPERATOR))
    page = client.get(reverse("emergencies:emergency_list")).context["page"]
    assert list(page.object_list) == [older, newer]


def test_action_owner_sees_panel_only_on_own(client, db, make_emergency):
    mine = make_emergency()
    other = make_emergency()
    add_prediction(mine, MUNICIPAL_RISK, {"level": 1, "k": 3})
    owner = make_user("omar", ACTION_OWNER)
    give_action(mine, owner)
    client.force_login(owner)
    own = client.get(reverse("emergencies:emergency_detail", args=[mine.pk]))
    assert own.status_code == 200
    assert "Risk level 1 of 3" in own.content.decode()
    assert client.get(reverse("emergencies:emergency_detail", args=[other.pk])).status_code == 404


NOT_ENOUGH_HISTORY = {"probability": None, "reason": "not_enough_history"}


def test_panel_replaces_old_estimate_with_not_enough_history(client, db, make_emergency):
    emergency = make_emergency()
    add_prediction(emergency, IMPACT, impact_output(0.63), score=0.63)
    add_prediction(emergency, IMPACT, NOT_ENOUGH_HISTORY)
    page = detail(client, emergency).content.decode()
    assert "Not enough history for this emergency type" in page
    assert "63 %" not in page
    assert "Estimated high-impact probability" not in page


def test_list_shows_dash_and_sorts_unknown_after_estimates(client, db, make_emergency):
    now = timezone.now()
    stale = make_emergency(occurred_at=now - timedelta(days=1))
    low = make_emergency(occurred_at=now - timedelta(days=2))
    add_prediction(stale, IMPACT, impact_output(0.95), score=0.95)
    add_prediction(stale, IMPACT, NOT_ENOUGH_HISTORY)
    add_prediction(low, IMPACT, impact_output(0.2), score=0.2)
    client.force_login(make_user("ana", OPERATOR))
    response = client.get(reverse("emergencies:emergency_list"))
    assert list(response.context["page"].object_list) == [low, stale]
    row = next(
        r
        for r in response.content.decode().split("<tr>")
        if reverse("emergencies:emergency_detail", args=[stale.pk]) in r
    )
    assert "—" in row
    assert "%" not in row
