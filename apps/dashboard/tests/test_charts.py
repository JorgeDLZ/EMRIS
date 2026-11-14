from datetime import timedelta

from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ADMINISTRATOR
from apps.dashboard.charts import Bar, bars
from apps.emergencies.models import Emergency, EmergencyType
from apps.places.models import Department, Municipality
from apps.seismic.models import SeismicEvent


def login(client):
    user = User.objects.create_user("ana", password="pass-12345")
    user.groups.add(Group.objects.get(name=ADMINISTRATOR))
    client.force_login(user)


def test_bars_scale_to_max():
    assert [bar.percent for bar in bars([("a", 4), ("b", 2)])] == [100, 50]


def test_bars_all_zero():
    assert [bar.percent for bar in bars([("a", 0)])] == [0]


def test_bars_keep_order():
    result = bars([("b", 1), ("a", 3), ("c", 2)])
    assert [bar.label for bar in result] == ["b", "a", "c"]
    assert result[0] == Bar("b", 1, 33)


def test_bar_step_rounds_to_multiple_of_five():
    assert [Bar("a", percent, percent).step for percent in (0, 2, 3, 33, 98, 100)] == [0, 5, 5, 35, 100, 100]


def test_dashboard_renders_bars(client, db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    flood = EmergencyType.objects.create(name="Flood")
    for _ in range(2):
        Emergency.objects.create(
            emergency_type=flood, municipality=municipality, occurred_at=timezone.now() - timedelta(hours=1)
        )
    login(client)
    html = client.get(reverse("dashboard:index")).content.decode()
    assert 'class="bar w-100"' in html
    assert "<span>2</span>" in html


def test_seismic_count_pluralised(client, db):
    SeismicEvent.objects.create(
        sgc_id="x", event_time=timezone.now(), magnitude=5.0, depth_km=1.0, latitude=4.0, longitude=-74.0, place="P"
    )
    login(client)
    html = client.get(reverse("dashboard:index")).content.decode()
    assert "1 event in the last 30 days of the catalog." in html


def test_small_non_zero_values_keep_a_visible_step():
    result = bars([("big", 1000), ("tiny", 1), ("none", 0)])
    assert [bar.step for bar in result] == [100, 5, 0]
