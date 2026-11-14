from datetime import date, timedelta
from urllib.parse import urljoin, urlsplit

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.emergencies.models import IN_RESPONSE, Emergency, EmergencyType, Impact
from apps.history.models import UngrdRecord
from apps.places.models import Department, Municipality
from apps.plans.models import KIT, Action, ActionPlan, Resource, ResourceAssignment

PASSWORD = "pass-12345"
ROLES = (ADMINISTRATOR, RISK_MANAGER, OPERATOR, ACTION_OWNER)


@pytest.fixture
def world(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    pending = Municipality.objects.create(
        department=department, name="NEW TOWN", validation=Municipality.PENDING
    )
    flood = EmergencyType.objects.create(name="Flood")
    users = {}
    for role in ROLES:
        users[role] = User.objects.create_user(role, password=PASSWORD)
        users[role].groups.add(Group.objects.get(name=role))
    emergency = Emergency.objects.create(
        emergency_type=flood,
        municipality=municipality,
        occurred_at=timezone.now() - timedelta(hours=1),
        status=IN_RESPONSE,
    )
    Impact.objects.create(emergency=emergency, deceased=1, people_affected=40)
    plan = ActionPlan.objects.create(emergency=emergency)
    action = Action.objects.create(
        plan=plan, description="Evacuate", owner=users[ACTION_OWNER], due_date=date.today()
    )
    resource = Resource.objects.create(name="Food kit", kind=KIT, quantity_available=10)
    assignment = ResourceAssignment.objects.create(plan=plan, resource=resource, quantity=2)
    UngrdRecord.objects.create(
        source_row=1,
        occurred_on=date(2020, 1, 10),
        department=department,
        municipality=municipality,
        emergency_type=flood,
        deceased=3,
        is_high_impact=True,
    )
    return {
        "users": users,
        "emergency": emergency,
        "action": action,
        "assignment": assignment,
        "resource": resource,
        "flood": flood,
        "pending": pending,
        "municipality": municipality,
    }


def page_urls(world):
    emergency = world["emergency"]
    return [
        reverse("home"),
        reverse("dashboard:index"),
        reverse("dashboard:ranking"),
        reverse("emergencies:emergency_list"),
        reverse("emergencies:emergency_create"),
        reverse("emergencies:emergency_detail", args=[emergency.pk]),
        reverse("emergencies:emergency_edit", args=[emergency.pk]),
        reverse("emergencies:impact_edit", args=[emergency.pk]),
        reverse("emergencies:type_list"),
        reverse("emergencies:type_create"),
        reverse("emergencies:type_edit", args=[world["flood"].pk]),
        reverse("plans:plan_detail", args=[emergency.pk]),
        reverse("plans:action_create", args=[emergency.pk]),
        reverse("plans:action_edit", args=[world["action"].pk]),
        reverse("plans:resource_list"),
        reverse("plans:resource_create"),
        reverse("plans:resource_edit", args=[world["resource"].pk]),
        reverse("history:record_list"),
        reverse("history:record_detail", args=[1]),
        reverse("places:municipality_list"),
        reverse("places:municipality_create"),
        reverse("places:municipality_pending"),
        reverse("accounts:user_list"),
        reverse("accounts:user_role", args=[world["users"][OPERATOR].pk]),
        reverse("intelligence:model_list"),
    ]


def logged_in(role):
    client = Client()
    assert client.login(username=role, password=PASSWORD)
    return client


def crawl(client, urls):
    pages = {}
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code)
        pages[url] = response.content.decode()
    return pages


def crawl_open_pages(client, urls):
    pages = {}
    for url in urls:
        response = client.get(url)
        assert response.status_code in (200, 403), (url, response.status_code)
        if response.status_code == 200:
            pages[url] = response.content.decode()
    return pages


@pytest.fixture
def admin_pages(world):
    pages = crawl(logged_in(ADMINISTRATOR), page_urls(world))
    anonymous = Client()
    pages.update(crawl(anonymous, [reverse("accounts:login"), reverse("accounts:register")]))
    return pages


def test_plan_page_audits_the_resource_assignment_form(admin_pages, world):
    html = admin_pages[reverse("plans:plan_detail", args=[world["emergency"].pk])]
    assert reverse("plans:assignment_create", args=[world["emergency"].pk]) in html


def test_every_page_has_one_h1_and_lang(admin_pages):
    for url, html in admin_pages.items():
        assert '<html lang="en">' in html, url
        soup = BeautifulSoup(html, "html.parser")
        assert len(soup.find_all("h1")) == 1, url
        assert soup.find(["h1", "h2", "h3", "h4"]).name == "h1", url


def test_every_table_is_wrapped(admin_pages):
    for url, html in admin_pages.items():
        for table in BeautifulSoup(html, "html.parser").find_all("table"):
            wrapper = table.find_parent(class_="table-wrap")
            assert wrapper is not None, url


def test_every_input_has_a_label(admin_pages):
    for url, html in admin_pages.items():
        soup = BeautifulSoup(html, "html.parser")
        labels = soup.find_all("label")
        assert not [label for label in labels if label.get_text(strip=True).endswith(":")], url
        labelled = {label["for"] for label in labels if label.get("for")}
        for field in soup.find_all(["input", "select", "textarea"]):
            if field.name == "input" and field.get("type") in ("hidden", "submit", "button"):
                continue
            assert field.get("id"), (url, field)
            assert field["id"] in labelled or field.get("aria-label"), (url, field)


def test_icon_only_controls_have_labels(admin_pages):
    for url, html in admin_pages.items():
        soup = BeautifulSoup(html, "html.parser")
        for control in soup.find_all(["button", "a"]):
            if control.get_text(strip=True) or control.get("aria-label"):
                continue
            assert control.get("aria-labelledby"), (url, control)


def internal_links(html, page_url="/"):
    links = set()
    for anchor in BeautifulSoup(html, "html.parser").find_all("a", href=True):
        if anchor["href"].startswith("#"):
            continue
        parts = urlsplit(urljoin(page_url, anchor["href"]))
        if parts.scheme in ("http", "https") and not parts.netloc.startswith("testserver"):
            continue
        if parts.scheme not in ("", "http", "https") or parts.path.startswith("/admin/"):
            continue
        links.add(parts.path + (f"?{parts.query}" if parts.query else ""))
    return links


@pytest.mark.parametrize("role", ROLES)
def test_no_link_leads_to_403_for_any_role(world, role):
    client = logged_in(role)
    pages = crawl_open_pages(client, page_urls(world))
    assert reverse("home") in pages
    links = set()
    for url, html in pages.items():
        links |= internal_links(html, url)
    assert links
    forbidden = [link for link in sorted(links) if client.get(link).status_code == 403]
    assert forbidden == []


def test_crawl_helper_ignores_fragments_and_external_links():
    html = '<a href="#top">x</a><a href="https://a.test/">y</a><a href="/ok/?a=1#z">z</a>'
    assert internal_links(html) == {"/ok/?a=1"}


def test_crawl_helper_resolves_query_only_links():
    html = '<a href="?page=2">next</a><a href="mailto:a@b.test">m</a>'
    assert internal_links(html, "/history/?type=1") == {"/history/?page=2"}
