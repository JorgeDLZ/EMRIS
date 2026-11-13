import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.emergencies.models import EmergencyType
from apps.history.models import UngrdRecord
from apps.places.models import Department, Municipality

PASSWORD = "pass-12345"


def make_user(username, role=None):
    user = User.objects.create_user(username, password=PASSWORD)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


@pytest.fixture
def world(db):
    antioquia = Department.objects.create(code="05", name="ANTIOQUIA")
    narino = Department.objects.create(code="52", name="NARIÑO")
    medellin = Municipality.objects.create(department=antioquia, code="05001", name="MEDELLÍN")
    pasto = Municipality.objects.create(department=narino, code="52001", name="PASTO")
    flood = EmergencyType.objects.create(name="Flood")
    fire = EmergencyType.objects.create(name="Fire")
    return {
        "antioquia": antioquia, "narino": narino, "medellin": medellin,
        "pasto": pasto, "flood": flood, "fire": fire,
    }


def make_record(row, **extra):
    return UngrdRecord.objects.create(source_row=row, **extra)


@pytest.fixture
def records(world):
    w = world
    return [
        make_record(1, occurred_on=date(2020, 1, 10), department=w["antioquia"],
                    municipality=w["medellin"], emergency_type=w["flood"], is_high_impact=True),
        make_record(2, occurred_on=date(2021, 5, 1), department=w["narino"],
                    municipality=w["pasto"], emergency_type=w["fire"]),
        make_record(3, occurred_on=date(2021, 5, 1), department=w["narino"],
                    municipality=w["pasto"], emergency_type=w["flood"]),
    ]


@pytest.fixture
def logged(client, db):
    client.force_login(make_user("ana", OPERATOR))
    return client


def listed_rows(response):
    return [record.source_row for record in response.context["page"]]


def test_list_filters_and_orders(logged, records, world):
    url = reverse("history:record_list")
    assert listed_rows(logged.get(url)) == [3, 2, 1]
    assert listed_rows(logged.get(url, {"type": world["fire"].pk})) == [2]
    assert listed_rows(logged.get(url, {"department": "05"})) == [1]
    assert listed_rows(logged.get(url, {"q": "medellin"})) == [1]
    assert listed_rows(logged.get(url, {"from": "2021-01-01"})) == [3, 2]
    assert listed_rows(logged.get(url, {"to": "2020-12-31"})) == [1]
    assert listed_rows(logged.get(url, {"high": "1"})) == [1]
    response = logged.get(url, {"department": "52", "high": "1"})
    assert listed_rows(response) == []
    html = response.content.decode()
    assert "No records match these filters." in html
    assert "0 records" in html
    assert "3 records" in logged.get(url).content.decode()


def test_invalid_filters_are_ignored(logged, records):
    url = reverse("history:record_list")
    response = logged.get(
        url, {"type": "abc", "from": "2025-13-40", "to": "x", "department": "999", "high": "2", "page": "999"}
    )
    assert response.status_code == 200
    assert response.context["cleaned"] == {
        "type": "", "department": "", "q": "", "from": "", "to": "", "high": "",
    }
    assert listed_rows(response) == [3, 2, 1]


def test_pagination_keeps_filters(logged, world):
    for row in range(1, 52):
        make_record(row, occurred_on=date(2020, 1, 1), department=world["antioquia"],
                    emergency_type=world["flood"])
    response = logged.get(reverse("history:record_list"), {"department": "05"})
    html = response.content.decode()
    assert "department=05" in html
    assert "page=2" in html


def test_detail_shows_impact_comments_and_actions(logged, world):
    make_record(
        7, occurred_on=date(2020, 2, 2), department=world["antioquia"],
        municipality=world["medellin"], emergency_type=world["flood"], source_code="A-7",
        deceased=4, hectares=2.5, comments="line one\nline two",
        action_codes=["clear_roads", "mystery_code"], is_high_impact=True,
    )
    response = logged.get(reverse("history:record_detail", args=[7]))
    html = response.content.decode()
    assert response.status_code == 200
    assert "UNGRD record 7" in html
    assert "A-7" in html
    assert "Deceased" in html and "Hectares" in html
    assert "<td>2.5</td>" in html
    assert "High impact: Yes" in html
    assert "line one<br>line two" in html
    assert "Clear and reopen roads" in html
    assert "mystery_code" in html
    assert "Back to the history" in html
    assert logged.get(reverse("history:record_detail", args=[999])).status_code == 404


def test_detail_without_actions(logged, world):
    make_record(8, occurred_on=date(2020, 2, 2), department=world["antioquia"],
                emergency_type=world["flood"])
    html = logged.get(reverse("history:record_detail", args=[8])).content.decode()
    assert "No actions recorded." in html
    assert "High impact: No" in html


def test_department_level_record(logged, world):
    make_record(9, occurred_on=date(2020, 2, 2), department=world["antioquia"],
                emergency_type=world["flood"])
    assert "Department level" in logged.get(reverse("history:record_list")).content.decode()
    assert "Department level" in logged.get(reverse("history:record_detail", args=[9])).content.decode()


@pytest.mark.parametrize("role", [ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER])
def test_every_role_can_browse(client, records, role):
    client.force_login(make_user(f"user-{role}", role))
    assert client.get(reverse("history:record_list")).status_code == 200
    assert client.get(reverse("history:record_detail", args=[1])).status_code == 200
    assert "History" in client.get(reverse("history:record_list")).content.decode()


def test_anonymous_user_goes_to_login(client, records):
    for url in (reverse("history:record_list"), reverse("history:record_detail", args=[1])):
        response = client.get(url)
        assert response.status_code == 302
        assert reverse("accounts:login") in response.url


def test_history_views_do_not_import_pandas():
    script = (
        "import os, sys, django\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
        "django.setup()\n"
        "import apps.history.views\n"
        "loaded = [name for name in ('pandas', 'sklearn') if name in sys.modules]\n"
        "sys.exit(','.join(loaded) or 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_oversized_type_is_ignored(logged, records):
    response = logged.get(reverse("history:record_list"), {"type": "99999999999"})
    assert response.status_code == 200
    assert response.context["cleaned"]["type"] == ""


def test_compact_date_is_normalized(logged, records):
    response = logged.get(reverse("history:record_list"), {"from": "20250101"})
    assert response.context["cleaned"]["from"] == "2025-01-01"


def test_detail_escapes_comments(logged, world):
    make_record(10, occurred_on=date(2020, 2, 2), department=world["antioquia"],
                emergency_type=world["flood"], comments="<script>alert(1)</script>\nsecond")
    html = logged.get(reverse("history:record_detail", args=[10])).content.decode()
    assert "&lt;script&gt;" in html
    assert "<br>" in html
    assert "<script>" not in html


def test_nul_bytes_are_removed_from_filters(logged, records):
    url = reverse("history:record_list")
    response = logged.get(url, {"q": "\x00", "department": "a\x00", "type": "\x00", "from": "\x00", "high": "\x00"})
    assert response.status_code == 200
    assert response.context["cleaned"] == {
        "type": "", "department": "", "q": "", "from": "", "to": "", "high": "",
    }
    response = logged.get(url, {"department": "05\x00", "q": "medel\x00lin", "type": f"{records[0].emergency_type_id}\x00"})
    assert response.status_code == 200
    assert response.context["cleaned"]["department"] == "05"
    assert response.context["cleaned"]["q"] == "medellin"
    assert "\x00" not in "".join(response.context["cleaned"].values())


def test_non_ascii_digit_type_is_ignored(logged, records):
    response = logged.get(reverse("history:record_list"), {"type": "²"})
    assert response.status_code == 200
    assert response.context["cleaned"]["type"] == ""
