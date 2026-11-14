import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import RISK_MANAGER
from apps.places.models import Department, Municipality

LIST_FILTERS = [
    ("emergencies:emergency_list", "id"),
    ("history:record_list", "code"),
    ("places:municipality_list", "id"),
]


@pytest.mark.parametrize(("url_name", "department_key"), LIST_FILTERS)
def test_list_filters_offer_municipality_search(client, db, url_name, department_key):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    user = User.objects.create_user("rita", password="pass-12345")
    user.groups.add(Group.objects.get(name=RISK_MANAGER))
    client.force_login(user)
    html = client.get(reverse(url_name)).content.decode()
    assert '<script id="municipality-options" type="application/json">' in html
    assert "MEDELL" in html.split('id="municipality-options"')[1].split("</script>")[0]
    assert 'data-combobox="municipality"' in html
    assert 'data-combobox-mode="text"' in html
    assert 'data-department-field="department"' in html
    if department_key == "code":
        assert 'data-department-key="code"' in html
    else:
        assert 'data-department-key="code"' not in html
