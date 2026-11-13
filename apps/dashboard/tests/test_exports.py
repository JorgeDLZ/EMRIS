import csv
import io
from datetime import date, datetime
from datetime import timezone as dt_timezone

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR
from apps.emergencies.models import Emergency, EmergencyType, Impact
from apps.history.models import UngrdRecord
from apps.intelligence.models import IMPACT, MUNICIPAL_RISK, PROFILES, ModelVersion, Prediction
from apps.places.models import Department, Municipality
from apps.plans.models import Action, ActionPlan

PASSWORD = "pass-12345"
EMERGENCY_HEADER = [
    "id", "occurred_at", "type", "municipality", "department", "status", "priority", "profile",
    "risk_level", "deceased", "injured", "missing", "people_affected", "families_affected",
    "homes_destroyed", "homes_damaged", "roads_damaged", "bridges_damaged", "hectares", "closed_at",
]
RANKING_HEADER = ["position", "municipality_code", "municipality", "department", "level", "k"]
HISTORY_HEADER = [
    "source_row", "occurred_on", "type", "department", "municipality", "deceased", "injured",
    "missing", "people_affected", "families_affected", "homes_destroyed", "homes_damaged",
    "roads_damaged", "bridges_damaged", "hectares", "is_high_impact", "actions",
]


def make_user(username, role):
    user = User.objects.create_user(username, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return user


def parse(response):
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text[1:])))


def make_version(component, **extra):
    values = {
        "component": component, "version": 1, "artifact": b"", "primary_metric": "m",
        "score": 0.5, "metrics": {}, "trained_on": {}, "library_versions": {},
    }
    values.update(extra)
    return ModelVersion.objects.create(**values)


def predict(emergency, component, output):
    version = make_version(component, version=Prediction.objects.count() + 1)
    return Prediction.objects.create(
        emergency=emergency, model_version=version, component=component, output=output
    )


@pytest.fixture
def world(db):
    department = Department.objects.create(code="11", name="BOGOTÁ, D.C.")
    municipality = Municipality.objects.create(department=department, code="11001", name="BOGOTÁ, D.C.")
    flood = EmergencyType.objects.create(name="Flood")

    def build(**extra):
        values = {
            "emergency_type": flood, "municipality": municipality,
            "occurred_at": datetime(2026, 3, 2, 2, 0, tzinfo=dt_timezone.utc),
        }
        values.update(extra)
        return Emergency.objects.create(**values)

    return {"department": department, "municipality": municipality, "flood": flood, "build": build}


def test_emergency_csv_has_header_and_rows(client, world):
    emergency = world["build"](status="in_response", description='He said "go", twice')
    Impact.objects.create(emergency=emergency, deceased=2, hectares=1.5)
    predict(emergency, IMPACT, {"probability": 0.1})
    predict(emergency, IMPACT, {"probability": 0.8766})
    predict(emergency, PROFILES, {"profile": "Flood wave"})
    predict(emergency, MUNICIPAL_RISK, {"level": 2, "k": 3})
    client.force_login(make_user("ana", OPERATOR))
    response = client.get(reverse("dashboard:export_emergencies"))
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv; charset=utf-8"
    assert response["Content-Disposition"] == 'attachment; filename="emergencies.csv"'
    rows = parse(response)
    assert rows[0] == EMERGENCY_HEADER
    assert rows[1] == [
        str(emergency.pk), "2026-03-01 21:00", "Flood", "BOGOTÁ, D.C.", "BOGOTÁ, D.C.",
        "In response", "0.877", "Flood wave", "2 of 3",
        "2", "0", "0", "0", "0", "0", "0", "0", "0", "1.5", "",
    ]
    assert len(rows) == 2


def test_emergency_csv_without_impact_or_predictions(client, world):
    emergency = world["build"](closed_at=datetime(2026, 3, 3, 15, 30, tzinfo=dt_timezone.utc))
    predict(emergency, IMPACT, {"probability": None})
    predict(emergency, MUNICIPAL_RISK, {"level": None, "k": 3})
    client.force_login(make_user("ana", OPERATOR))
    row = parse(client.get(reverse("dashboard:export_emergencies")))[1]
    assert row[6:9] == ["", "", "Insufficient history"]
    assert row[9:19] == [""] * 10
    assert row[19] == "2026-03-03 10:30"


def test_emergency_csv_is_newest_first(client, world):
    old = world["build"](occurred_at=datetime(2025, 1, 1, tzinfo=dt_timezone.utc))
    new = world["build"]()
    client.force_login(make_user("ana", OPERATOR))
    rows = parse(client.get(reverse("dashboard:export_emergencies")))
    assert [row[0] for row in rows[1:]] == [str(new.pk), str(old.pk)]


def test_action_owner_csv_has_only_own(client, world):
    owner = make_user("owen", ACTION_OWNER)
    own = world["build"]()
    world["build"]()
    world["build"]()
    plan = ActionPlan.objects.create(emergency=own)
    Action.objects.create(plan=plan, description="Deliver kits", owner=owner)
    Action.objects.create(plan=plan, description="Open shelter", owner=owner)
    client.force_login(owner)
    rows = parse(client.get(reverse("dashboard:export_emergencies")))
    assert [row[0] for row in rows[1:]] == [str(own.pk)]


def test_csv_keeps_commas_quotes_and_accents(client, world):
    world["build"](description='He said "go", twice')
    client.force_login(make_user("ana", ADMINISTRATOR))
    response = client.get(reverse("dashboard:export_emergencies"))
    rows = parse(response)
    assert rows[1][3] == "BOGOTÁ, D.C."
    assert '"BOGOTÁ, D.C."' in response.content.decode("utf-8")


def test_ranking_csv_forbidden_for_action_owner(client, world):
    make_version(
        MUNICIPAL_RISK, metrics={"k": 3}, is_active=True,
        metadata={"ranking": [
            {"code": "11001", "level": 1, "score": 0.1},
            {"code": "99999", "level": 3, "score": 0.9},
        ]},
    )
    client.force_login(make_user("owen", ACTION_OWNER))
    assert client.get(reverse("dashboard:export_ranking")).status_code == 403
    client.force_login(make_user("root", ADMINISTRATOR))
    response = client.get(reverse("dashboard:export_ranking"))
    assert response["Content-Disposition"] == 'attachment; filename="municipal_risk_ranking.csv"'
    assert parse(response) == [
        RANKING_HEADER,
        ["1", "99999", "99999", "", "3", "3"],
        ["2", "11001", "BOGOTÁ, D.C.", "BOGOTÁ, D.C.", "1", "3"],
    ]


def test_ranking_csv_follows_department(client, world):
    other = Department.objects.create(code="05", name="ANTIOQUIA")
    Municipality.objects.create(department=other, code="05001", name="MEDELLÍN")
    make_version(
        MUNICIPAL_RISK, metrics={"k": 3}, is_active=True,
        metadata={"ranking": [
            {"code": "11001", "level": 1, "score": 0.1},
            {"code": "05001", "level": 2, "score": 0.5},
        ]},
    )
    client.force_login(make_user("root", ADMINISTRATOR))
    rows = parse(client.get(reverse("dashboard:export_ranking"), {"department": "05"}))
    assert [row[1] for row in rows[1:]] == ["05001"]


def test_history_csv_follows_filters(client, world):
    antioquia = Department.objects.create(code="05", name="ANTIOQUIA")
    UngrdRecord.objects.create(
        source_row=1, occurred_on=date(2020, 1, 10), department=world["department"],
        municipality=world["municipality"], emergency_type=world["flood"], is_high_impact=True,
        deceased=3, hectares=2.5, action_codes=["clear_roads", "mystery_code"],
    )
    UngrdRecord.objects.create(
        source_row=2, occurred_on=date(2021, 5, 1), department=antioquia,
        emergency_type=world["flood"],
    )
    client.force_login(make_user("ana", OPERATOR))
    url = reverse("history:export")
    everything = parse(client.get(url))
    assert everything[0] == HISTORY_HEADER
    assert [row[0] for row in everything[1:]] == ["2", "1"]
    assert everything[1][4] == ""
    response = client.get(url, {"high": "1"})
    assert response["Content-Disposition"] == 'attachment; filename="ungrd_history.csv"'
    assert parse(response)[1:] == [[
        "1", "2020-01-10", "Flood", "BOGOTÁ, D.C.", "BOGOTÁ, D.C.", "3", "0", "0", "0", "0", "0",
        "0", "0", "0", "2.5", "true", "Clear and reopen roads; mystery_code",
    ]]


def test_action_owner_can_export_history(client, world):
    client.force_login(make_user("owen", ACTION_OWNER))
    assert client.get(reverse("history:export")).status_code == 200


def test_empty_exports(client, world):
    client.force_login(make_user("root", ADMINISTRATOR))
    assert parse(client.get(reverse("dashboard:export_emergencies"))) == [EMERGENCY_HEADER]
    assert parse(client.get(reverse("dashboard:export_ranking"))) == [RANKING_HEADER]
    assert parse(client.get(reverse("history:export"))) == [HISTORY_HEADER]


def test_anonymous_user_goes_to_login(client, db):
    for name in ("dashboard:export_emergencies", "dashboard:export_ranking", "history:export"):
        assert client.get(reverse(name)).status_code == 302


def test_download_links(client, world):
    make_version(
        MUNICIPAL_RISK, metrics={"k": 3}, is_active=True,
        metadata={"ranking": [{"code": "11001", "level": 1, "score": 0.1}]},
    )
    client.force_login(make_user("root", ADMINISTRATOR))
    assert reverse("dashboard:export_emergencies") in client.get(reverse("dashboard:index")).content.decode()
    assert reverse("dashboard:export_ranking") in client.get(reverse("dashboard:ranking")).content.decode()
    html = client.get(reverse("history:record_list"), {"high": "1"}).content.decode()
    assert f'{reverse("history:export")}?high=1' in html
    client.force_login(make_user("owen", ACTION_OWNER))
    html = client.get(reverse("dashboard:index")).content.decode()
    assert reverse("dashboard:export_emergencies") in html
    assert reverse("dashboard:export_ranking") not in html


def test_csv_cells_starting_with_formula_characters_are_quoted(client, world):
    formula = '=HYPERLINK("http://x","y")'
    municipality = Municipality.objects.create(
        department=world["department"], code="11002", name=formula
    )
    emergency = world["build"](municipality=municipality)
    Impact.objects.create(emergency=emergency, deceased=2)
    client.force_login(make_user("ana", ADMINISTRATOR))
    rows = parse(client.get(reverse("dashboard:export_emergencies")))
    assert rows[0] == EMERGENCY_HEADER
    row = next(row for row in rows[1:] if row[0] == str(emergency.pk))
    assert row[3] == "'" + formula
    assert row[9] == "2"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_response_quotes_every_formula_prefix(prefix):
    from apps.dashboard.exports import csv_response

    response = csv_response("x.csv", ["a", "-b"], [[prefix + "x", 5, -1.5, "plain"]])
    rows = parse(response)
    assert rows[0] == ["a", "-b"]
    assert rows[1] == ["'" + prefix + "x", "5", "-1.5", "plain"]
