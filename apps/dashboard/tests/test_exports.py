from datetime import date, datetime
from datetime import timezone as dt_timezone
from io import BytesIO

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from openpyxl import load_workbook

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR
from apps.emergencies.models import Emergency, EmergencyType, Impact
from apps.history.models import UngrdRecord
from apps.intelligence.models import IMPACT, MUNICIPAL_RISK, PROFILES, ModelVersion, Prediction
from apps.places.models import Department, Municipality
from apps.plans.models import Action, ActionPlan

PASSWORD = "pass-12345"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HIGHLIGHT = "00FCE4E4"
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


def sheet(response):
    assert response["Content-Type"] == XLSX_TYPE
    return load_workbook(BytesIO(response.content)).active


def values(worksheet):
    return [[cell.value for cell in row] for row in worksheet.iter_rows()]


def fills(worksheet):
    return [
        row[0].fill.fgColor.rgb if row[0].fill.fill_type else None
        for row in worksheet.iter_rows(min_row=2)
    ]


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


def test_emergency_workbook_header_and_style(client, world):
    world["build"]()
    client.force_login(make_user("ana", OPERATOR))
    response = client.get(reverse("dashboard:export_emergencies"))
    assert response.status_code == 200
    assert response["Content-Disposition"] == 'attachment; filename="emergencies.xlsx"'
    worksheet = sheet(response)
    assert worksheet.title == "Emergencies"
    assert values(worksheet)[0] == EMERGENCY_HEADER
    first = worksheet["A1"]
    assert first.font.bold
    assert first.font.color.rgb == "00FFFFFF"
    assert first.fill.fgColor.rgb == "001F4E78"
    assert worksheet.freeze_panes == "A2"
    assert worksheet.auto_filter.ref == f"A1:T{worksheet.max_row}"
    assert 8 <= worksheet.column_dimensions["D"].width <= 50


def test_emergency_workbook_typed_values(client, world):
    emergency = world["build"](
        status="in_response", closed_at=datetime(2026, 3, 3, 15, 30, tzinfo=dt_timezone.utc)
    )
    Impact.objects.create(emergency=emergency, deceased=2, hectares=1.5)
    predict(emergency, IMPACT, {"probability": 0.1, "is_high_impact": False})
    predict(emergency, IMPACT, {"probability": 0.8766, "is_high_impact": False})
    predict(emergency, PROFILES, {"profile": "Flood wave"})
    predict(emergency, MUNICIPAL_RISK, {"level": 2, "k": 3})
    client.force_login(make_user("ana", OPERATOR))
    worksheet = sheet(client.get(reverse("dashboard:export_emergencies")))
    assert values(worksheet)[1] == [
        emergency.pk, datetime(2026, 3, 1, 21, 0), "Flood", "BOGOTÁ, D.C.", "BOGOTÁ, D.C.",
        "In response", 0.877, "Flood wave", "2 of 3",
        2, 0, 0, 0, 0, 0, 0, 0, 0, 1.5, datetime(2026, 3, 3, 10, 30),
    ]
    assert worksheet["B2"].number_format == "yyyy-mm-dd hh:mm"
    assert worksheet["T2"].number_format == "yyyy-mm-dd hh:mm"
    assert worksheet["G2"].number_format == "0.000"


def test_emergency_workbook_without_impact_or_predictions(client, world):
    emergency = world["build"]()
    predict(emergency, IMPACT, {"probability": None, "reason": "not_enough_history"})
    predict(emergency, MUNICIPAL_RISK, {"level": None, "k": 3})
    client.force_login(make_user("ana", OPERATOR))
    row = values(sheet(client.get(reverse("dashboard:export_emergencies"))))[1]
    assert row[6:9] == [None, None, "Insufficient history"]
    assert row[9:19] == [None] * 10
    assert row[19] is None


def test_emergency_workbook_is_newest_first(client, world):
    old = world["build"](occurred_at=datetime(2025, 1, 1, tzinfo=dt_timezone.utc))
    new = world["build"]()
    client.force_login(make_user("ana", OPERATOR))
    rows = values(sheet(client.get(reverse("dashboard:export_emergencies"))))
    assert [row[0] for row in rows[1:]] == [new.pk, old.pk]


def test_high_impact_rows_highlighted(client, world):
    high = world["build"]()
    low = world["build"](occurred_at=datetime(2025, 1, 1, tzinfo=dt_timezone.utc))
    predict(high, IMPACT, {"probability": 0.9, "is_high_impact": True})
    predict(low, IMPACT, {"probability": 0.1, "is_high_impact": False})
    client.force_login(make_user("ana", OPERATOR))
    worksheet = sheet(client.get(reverse("dashboard:export_emergencies")))
    assert fills(worksheet) == [HIGHLIGHT, None]
    assert all(cell.fill.fgColor.rgb == HIGHLIGHT for cell in worksheet[2])


def test_formula_like_text_stays_text(client, world):
    formula = '=HYPERLINK("http://x","y")'
    municipality = Municipality.objects.create(
        department=world["department"], code="11002", name=formula
    )
    world["build"](municipality=municipality)
    client.force_login(make_user("ana", ADMINISTRATOR))
    cell = sheet(client.get(reverse("dashboard:export_emergencies")))["D2"]
    assert cell.value == formula
    assert cell.data_type == "s"


def test_action_owner_workbook_has_only_own(client, world):
    owner = make_user("owen", ACTION_OWNER)
    own = world["build"]()
    world["build"]()
    world["build"]()
    plan = ActionPlan.objects.create(emergency=own)
    Action.objects.create(plan=plan, description="Deliver kits", owner=owner)
    Action.objects.create(plan=plan, description="Open shelter", owner=owner)
    client.force_login(owner)
    rows = values(sheet(client.get(reverse("dashboard:export_emergencies"))))
    assert [row[0] for row in rows[1:]] == [own.pk]


def test_ranking_workbook_forbidden_for_action_owner(client, world):
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
    assert response["Content-Disposition"] == 'attachment; filename="municipal_risk_ranking.xlsx"'
    worksheet = sheet(response)
    assert worksheet.title == "Municipal risk ranking"
    assert values(worksheet) == [
        RANKING_HEADER,
        [1, "99999", "99999", None, 3, 3],
        [2, "11001", "BOGOTÁ, D.C.", "BOGOTÁ, D.C.", 1, 3],
    ]
    assert fills(worksheet) == [HIGHLIGHT, None]


def test_ranking_workbook_follows_department(client, world):
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
    rows = values(sheet(client.get(reverse("dashboard:export_ranking"), {"department": "05"})))
    assert [row[1] for row in rows[1:]] == ["05001"]


def test_history_workbook_follows_filters(client, world):
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
    everything = sheet(client.get(url))
    assert values(everything)[0] == HISTORY_HEADER
    assert [row[0] for row in values(everything)[1:]] == [2, 1]
    assert values(everything)[1][4] is None
    assert fills(everything) == [None, HIGHLIGHT]
    response = client.get(url, {"high": "1"})
    assert response["Content-Disposition"] == 'attachment; filename="ungrd_history.xlsx"'
    worksheet = sheet(response)
    assert worksheet.title == "UNGRD history"
    assert values(worksheet)[1:] == [[
        1, datetime(2020, 1, 10), "Flood", "BOGOTÁ, D.C.", "BOGOTÁ, D.C.", 3, 0, 0, 0, 0, 0,
        0, 0, 0, 2.5, "Yes", "Clear and reopen roads; mystery_code",
    ]]
    assert worksheet["B2"].number_format == "yyyy-mm-dd"
    assert fills(worksheet) == [HIGHLIGHT]


def test_history_export_follows_browse_right(client, world):
    client.force_login(make_user("owen", ACTION_OWNER))
    assert client.get(reverse("history:export")).status_code == 403
    client.force_login(make_user("olga", OPERATOR))
    assert client.get(reverse("history:export")).status_code == 200


def test_empty_workbooks(client, world):
    client.force_login(make_user("root", ADMINISTRATOR))
    assert values(sheet(client.get(reverse("dashboard:export_emergencies")))) == [EMERGENCY_HEADER]
    assert values(sheet(client.get(reverse("dashboard:export_ranking")))) == [RANKING_HEADER]
    assert values(sheet(client.get(reverse("history:export")))) == [HISTORY_HEADER]


def test_anonymous_user_goes_to_login(client, db):
    for name in ("dashboard:export_emergencies", "dashboard:export_ranking", "history:export"):
        assert client.get(reverse(name)).status_code == 302


def test_download_links(client, world):
    make_version(
        MUNICIPAL_RISK, metrics={"k": 3}, is_active=True,
        metadata={"ranking": [{"code": "11001", "level": 1, "score": 0.1}]},
    )
    client.force_login(make_user("root", ADMINISTRATOR))
    dashboard = client.get(reverse("dashboard:index")).content.decode()
    assert reverse("dashboard:export_emergencies") in dashboard
    assert "Download Excel" in dashboard
    assert reverse("dashboard:export_ranking") in client.get(reverse("dashboard:ranking")).content.decode()
    html = client.get(reverse("history:record_list"), {"high": "1"}).content.decode()
    assert f'{reverse("history:export")}?high=1' in html
    client.force_login(make_user("owen", ACTION_OWNER))
    html = client.get(reverse("dashboard:index")).content.decode()
    assert reverse("dashboard:export_emergencies") in html
    assert reverse("dashboard:export_ranking") not in html


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_workbook_stores_every_text_as_text(prefix):
    from apps.dashboard.exports import xlsx_response

    response = xlsx_response("x.xlsx", "Sheet", [prefix + "a", "b"], [[prefix + "SUM(1,2)", 5]])
    worksheet = sheet(response)
    assert values(worksheet) == [[prefix + "a", "b"], [prefix + "SUM(1,2)", 5]]
    assert worksheet["A1"].data_type == "s"
    assert worksheet["A2"].data_type == "s"
    assert worksheet["B2"].data_type == "n"
