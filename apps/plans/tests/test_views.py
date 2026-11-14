import re
from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.roles import ACTION_OWNER, ADMINISTRATOR, OPERATOR, RISK_MANAGER
from apps.emergencies.models import CLOSED, REPORTED, Emergency, EmergencyType
from apps.history.models import UngrdRecord
from apps.intelligence import services
from apps.intelligence.models import SIMILARITY, Prediction
from apps.intelligence.training import activate_version, save_version, train_component
from apps.places.models import Department, Municipality
from apps.plans.models import (
    ACTION_CODE_CHOICES,
    APPROVED,
    DRAFT,
    IN_PROGRESS,
    KIT,
    PENDING,
    Action,
    ActionPlan,
    Resource,
    ResourceAssignment,
)
from ml.tests.conftest import make_synthetic_frame

PASSWORD = "pass-12345"


def make_user(username, role=None):
    user = User.objects.create_user(username, password=PASSWORD)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def login(client, user):
    client.login(username=user.username, password=PASSWORD)
    return client


@pytest.fixture
def make_emergency(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(department=department, code="05001", name="MEDELLÍN")
    flood = EmergencyType.objects.create(name="Flood")

    def build(status=REPORTED):
        return Emergency.objects.create(
            emergency_type=flood,
            municipality=municipality,
            occurred_at=timezone.now() - timedelta(hours=1),
            status=status,
        )

    return build


def test_operator_drafts_plan_but_cannot_approve(client, make_emergency):
    emergency = make_emergency()
    login(client, make_user("operator", OPERATOR))

    response = client.post(reverse("plans:plan_start", args=[emergency.pk]))
    assert response.status_code == 302
    assert ActionPlan.objects.filter(emergency=emergency).exists()

    response = client.post(
        reverse("plans:action_create", args=[emergency.pk]),
        {"description": "Evacuate the area", "code": "", "owner": "", "due_date": ""},
    )
    assert response.status_code == 302
    assert emergency.action_plan.actions.count() == 1

    response = client.post(reverse("plans:plan_approve", args=[emergency.pk]))
    assert response.status_code == 403
    assert not ActionPlan.objects.get(emergency=emergency).is_approved


def test_risk_manager_approves(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    Action.objects.create(plan=plan, description="Evacuate")

    login(client, make_user("manager", RISK_MANAGER))
    response = client.post(reverse("plans:plan_approve", args=[emergency.pk]))
    assert response.status_code == 302
    plan.refresh_from_db()
    assert plan.status == APPROVED

    login(client, make_user("operator", OPERATOR))
    response = client.post(
        reverse("plans:action_create", args=[emergency.pk]), {"description": "More"}
    )
    assert response.status_code == 403
    assert plan.actions.count() == 1


def test_action_owner_advances_own_action_only(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    owner = make_user("owner", ACTION_OWNER)
    other = make_user("other", ACTION_OWNER)
    own_action = Action.objects.create(plan=plan, description="Own", owner=owner)
    other_action = Action.objects.create(plan=plan, description="Other", owner=other)

    login(client, owner)
    assert client.get(reverse("plans:plan_detail", args=[emergency.pk])).status_code == 200
    response = client.post(reverse("plans:action_advance", args=[own_action.pk]))
    assert response.status_code == 302
    own_action.refresh_from_db()
    assert own_action.status == IN_PROGRESS

    response = client.post(reverse("plans:action_advance", args=[other_action.pk]))
    assert response.status_code == 403
    other_action.refresh_from_db()
    assert other_action.status != IN_PROGRESS


def test_action_owner_cannot_open_unrelated_plan(client, make_emergency):
    emergency = make_emergency()
    ActionPlan.objects.create(emergency=emergency)
    login(client, make_user("owner", ACTION_OWNER))
    assert client.get(reverse("plans:plan_detail", args=[emergency.pk])).status_code == 404


def test_assignment_over_remaining_is_form_error(client, make_emergency):
    emergency = make_emergency()
    ActionPlan.objects.create(emergency=emergency)
    kits = Resource.objects.create(name="Food kits", kind=KIT, quantity_available=10)
    other_plan = ActionPlan.objects.create(emergency=make_emergency())
    ResourceAssignment.objects.create(plan=other_plan, resource=kits, quantity=6)

    login(client, make_user("operator", OPERATOR))
    response = client.post(
        reverse("plans:assignment_create", args=[emergency.pk]),
        {"resource": kits.pk, "quantity": 7},
    )
    assert response.status_code == 200
    assert "Only 4 Food kits remain." in response.content.decode()
    assert not ResourceAssignment.objects.filter(plan=emergency.action_plan).exists()

    response = client.post(
        reverse("plans:assignment_create", args=[emergency.pk]),
        {"resource": kits.pk, "quantity": 0},
    )
    assert response.status_code == 200
    assert not ResourceAssignment.objects.filter(plan=emergency.action_plan).exists()

    response = client.post(
        reverse("plans:assignment_create", args=[emergency.pk]),
        {"resource": kits.pk, "quantity": 4},
    )
    assert response.status_code == 302
    assert ResourceAssignment.objects.get(plan=emergency.action_plan).quantity == 4


def test_resources_page_access(client, db):
    url = reverse("plans:resource_list")
    for username, role, status in [
        ("admin", ADMINISTRATOR, 200),
        ("manager", RISK_MANAGER, 200),
        ("operator", OPERATOR, 403),
        ("owner", ACTION_OWNER, 403),
    ]:
        login(client, make_user(username, role))
        assert client.get(url).status_code == status


def test_resource_pages_create_and_edit(client, db):
    login(client, make_user("admin", ADMINISTRATOR))
    response = client.post(
        reverse("plans:resource_create"),
        {"name": "Food kit", "kind": KIT, "quantity_available": 5},
    )
    assert response.status_code == 302
    resource = Resource.objects.get(name="Food kit")

    response = client.post(
        reverse("plans:resource_edit", args=[resource.pk]),
        {"name": "Food kit", "kind": KIT, "quantity_available": 9},
    )
    assert response.status_code == 302
    resource.refresh_from_db()
    assert resource.quantity_available == 9
    assert "Food kit" in client.get(reverse("plans:resource_list")).content.decode()


def test_resource_duplicate_name(client, db):
    Resource.objects.create(name="Food kit", kind=KIT, quantity_available=5)
    login(client, make_user("admin", ADMINISTRATOR))
    response = client.post(
        reverse("plans:resource_create"),
        {"name": "food kit", "kind": KIT, "quantity_available": 3},
    )
    assert response.status_code == 200
    assert "A resource with this name already exists." in response.content.decode()
    assert Resource.objects.count() == 1


def test_closed_emergency_plan_posts_refused(client, make_emergency):
    emergency = make_emergency(status=CLOSED)
    plan = ActionPlan.objects.create(emergency=emergency)
    owner = make_user("owner", ACTION_OWNER)
    action = Action.objects.create(plan=plan, description="Own", owner=owner)
    resource = Resource.objects.create(name="Food kits", kind=KIT, quantity_available=10)
    assignment = ResourceAssignment.objects.create(plan=plan, resource=resource, quantity=1)

    login(client, make_user("admin", ADMINISTRATOR))
    assert client.post(reverse("plans:plan_start", args=[emergency.pk])).status_code == 403
    assert (
        client.post(
            reverse("plans:action_create", args=[emergency.pk]), {"description": "x"}
        ).status_code
        == 403
    )
    assert client.post(reverse("plans:action_advance", args=[action.pk])).status_code == 403
    assert (
        client.post(
            reverse("plans:assignment_create", args=[emergency.pk]),
            {"resource": resource.pk, "quantity": 1},
        ).status_code
        == 403
    )
    assert client.post(reverse("plans:assignment_remove", args=[assignment.pk])).status_code == 403
    assert client.post(reverse("plans:plan_approve", args=[emergency.pk])).status_code == 403


def test_state_changing_views_are_post_only(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    action = Action.objects.create(plan=plan, description="x")
    resource = Resource.objects.create(name="Food kits", kind=KIT, quantity_available=10)
    assignment = ResourceAssignment.objects.create(plan=plan, resource=resource, quantity=1)

    login(client, make_user("admin", ADMINISTRATOR))
    for name, args in [
        ("plans:plan_start", [emergency.pk]),
        ("plans:plan_approve", [emergency.pk]),
        ("plans:action_advance", [action.pk]),
        ("plans:assignment_create", [emergency.pk]),
        ("plans:assignment_remove", [assignment.pk]),
    ]:
        assert client.get(reverse(name, args=args)).status_code == 405


def test_emergency_detail_shows_plan_block(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    owner = make_user("owner", ACTION_OWNER)
    action = Action.objects.create(plan=plan, description="Open shelter", owner=owner)
    Action.objects.create(plan=plan, description="Someone else's")

    login(client, owner)
    html = client.get(reverse("emergencies:emergency_detail", args=[emergency.pk])).content.decode()
    assert "Open shelter" in html
    assert reverse("plans:action_advance", args=[action.pk]) in html
    other = Action.objects.get(description="Someone else's")
    assert reverse("plans:action_advance", args=[other.pk]) not in html


def test_emergency_closed_after_policy_check_is_handled(client, make_emergency, monkeypatch):
    emergency = make_emergency(status=CLOSED)
    plan = ActionPlan.objects.create(emergency=emergency)
    action = Action.objects.create(plan=plan, description="x")
    resource = Resource.objects.create(name="Food kits", kind=KIT, quantity_available=10)
    assignment = ResourceAssignment.objects.create(plan=plan, resource=resource, quantity=1)
    for name in ("can_start_plan", "can_approve_plan", "can_edit_plan", "can_update_action"):
        monkeypatch.setattr(f"apps.plans.views.{name}", lambda *args: True)

    login(client, make_user("admin", ADMINISTRATOR))
    message = "This emergency is closed."

    for name, args in [
        ("plans:plan_start", [emergency.pk]),
        ("plans:plan_approve", [emergency.pk]),
        ("plans:action_advance", [action.pk]),
        ("plans:assignment_remove", [assignment.pk]),
    ]:
        response = client.post(reverse(name, args=args), follow=True)
        assert message in response.content.decode()

    response = client.post(
        reverse("plans:action_create", args=[emergency.pk]), {"description": "x"}
    )
    assert response.status_code == 200
    assert message in response.content.decode()

    response = client.post(
        reverse("plans:action_edit", args=[action.pk]), {"description": "y"}
    )
    assert response.status_code == 200
    assert message in response.content.decode()

    response = client.post(
        reverse("plans:assignment_create", args=[emergency.pk]),
        {"resource": resource.pk, "quantity": 1},
    )
    assert response.status_code == 200
    assert message in response.content.decode()


def test_repeated_approve_shows_message(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    Action.objects.create(plan=plan, description="Evacuate")
    login(client, make_user("manager", RISK_MANAGER))
    url = reverse("plans:plan_approve", args=[emergency.pk])

    assert client.post(url).status_code == 302
    response = client.post(url, follow=True)
    assert response.redirect_chain[-1][0] == reverse("plans:plan_detail", args=[emergency.pk])
    assert "This plan is already approved." in response.content.decode()
    plan.refresh_from_db()
    assert plan.status == APPROVED


def test_advance_forms_post_the_current_status(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    Action.objects.create(plan=plan, description="Evacuate")
    login(client, make_user("operator", OPERATOR))
    hidden = '<input type="hidden" name="expected_status" value="pending">'
    for url in (
        reverse("plans:plan_detail", args=[emergency.pk]),
        reverse("emergencies:emergency_detail", args=[emergency.pk]),
    ):
        assert hidden in client.get(url).content.decode()


def test_double_advance_moves_action_once(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    action = Action.objects.create(plan=plan, description="Evacuate")
    login(client, make_user("operator", OPERATOR))
    url = reverse("plans:action_advance", args=[action.pk])

    assert client.post(url, {"expected_status": PENDING}).status_code == 302
    response = client.post(url, {"expected_status": PENDING}, follow=True)
    assert response.redirect_chain[-1][0] == reverse("plans:plan_detail", args=[emergency.pk])
    assert "This action was already updated." in response.content.decode()
    action.refresh_from_db()
    assert action.status == IN_PROGRESS


def test_stock_below_assigned_is_saved_with_warning(client, make_emergency):
    kits = Resource.objects.create(name="Food kits", kind=KIT, quantity_available=10)
    plan = ActionPlan.objects.create(emergency=make_emergency())
    ResourceAssignment.objects.create(plan=plan, resource=kits, quantity=6)
    closed_plan = ActionPlan.objects.create(emergency=make_emergency(status=CLOSED))
    ResourceAssignment.objects.create(plan=closed_plan, resource=kits, quantity=50)
    login(client, make_user("admin", ADMINISTRATOR))
    url = reverse("plans:resource_edit", args=[kits.pk])

    response = client.post(
        url, {"name": "Food kits", "kind": KIT, "quantity_available": 4}, follow=True
    )
    assert response.redirect_chain[-1][0] == reverse("plans:resource_list")
    kits.refresh_from_db()
    assert kits.quantity_available == 4
    html = response.content.decode()
    assert "6 are assigned to open emergencies; the stock is now below that." in html
    assert "Over-assigned by 2" in html

    response = client.post(
        url, {"name": "Food kits", "kind": KIT, "quantity_available": 6}, follow=True
    )
    html = response.content.decode()
    assert "the stock is now below that" not in html
    assert "Over-assigned" not in html


def test_action_edit_on_closed_emergency_is_refused(client, make_emergency):
    emergency = make_emergency(status=CLOSED)
    plan = ActionPlan.objects.create(emergency=emergency)
    action = Action.objects.create(plan=plan, description="x")
    login(client, make_user("admin", ADMINISTRATOR))
    url = reverse("plans:action_edit", args=[action.pk])
    assert client.get(url).status_code == 403
    assert client.post(url, {"description": "y"}).status_code == 403
    action.refresh_from_db()
    assert action.description == "x"


def test_action_owner_cannot_change_the_plan(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    owner = make_user("owner", ACTION_OWNER)
    action = Action.objects.create(plan=plan, description="Own", owner=owner)
    resource = Resource.objects.create(name="Food kits", kind=KIT, quantity_available=10)
    assignment = ResourceAssignment.objects.create(plan=plan, resource=resource, quantity=1)

    login(client, owner)
    pk = [emergency.pk]
    assert client.post(reverse("plans:plan_start", args=pk)).status_code == 403
    assert client.post(reverse("plans:plan_approve", args=pk)).status_code == 403
    assert client.get(reverse("plans:action_create", args=pk)).status_code == 403
    assert (
        client.post(reverse("plans:action_create", args=pk), {"description": "x"}).status_code
        == 403
    )
    assert client.get(reverse("plans:action_edit", args=[action.pk])).status_code == 403
    assert (
        client.post(
            reverse("plans:action_edit", args=[action.pk]), {"description": "y"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            reverse("plans:assignment_create", args=pk), {"resource": resource.pk, "quantity": 2}
        ).status_code
        == 403
    )
    assert client.post(reverse("plans:assignment_remove", args=[assignment.pk])).status_code == 403
    plan.refresh_from_db()
    action.refresh_from_db()
    assignment.refresh_from_db()
    assert (plan.status, plan.actions.count(), action.description) == (DRAFT, 1, "Own")
    assert assignment.quantity == 1


def test_operator_cannot_change_an_approved_plan(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency, status=APPROVED)
    action = Action.objects.create(plan=plan, description="x")
    resource = Resource.objects.create(name="Food kits", kind=KIT, quantity_available=10)
    assignment = ResourceAssignment.objects.create(plan=plan, resource=resource, quantity=1)

    login(client, make_user("operator", OPERATOR))
    assert (
        client.post(
            reverse("plans:assignment_create", args=[emergency.pk]),
            {"resource": resource.pk, "quantity": 2},
        ).status_code
        == 403
    )
    assert client.post(reverse("plans:assignment_remove", args=[assignment.pk])).status_code == 403
    edit_url = reverse("plans:action_edit", args=[action.pk])
    assert client.get(edit_url).status_code == 403
    assert client.post(edit_url, {"description": "y"}).status_code == 403
    action.refresh_from_db()
    assignment.refresh_from_db()
    assert (action.description, assignment.quantity) == ("x", 1)


CODE, LABEL = ACTION_CODE_CHOICES[0]


@pytest.fixture(scope="module")
def similarity_model():
    return train_component(SIMILARITY, make_synthetic_frame(), {})


@pytest.fixture
def active_similarity(db, similarity_model):
    services.clear_cache()
    version = save_version(SIMILARITY, similarity_model, None, None)
    activate_version(version)
    yield version
    services.clear_cache()


def store_prediction(emergency, version, neighbors, actions):
    return Prediction.objects.create(
        emergency=emergency,
        model_version=version,
        component=SIMILARITY,
        output={"neighbors": neighbors, "suggested_actions": actions},
    )


def test_suggest_stores_and_shows_cases(client, make_emergency, active_similarity):
    emergency = make_emergency()
    login(client, make_user("operator", OPERATOR))
    url = reverse("plans:plan_suggest", args=[emergency.pk])

    response = client.post(url, follow=True)
    assert response.redirect_chain[-1][0] == reverse("plans:plan_detail", args=[emergency.pk])
    assert "Similar emergencies were found." in response.content.decode()
    assert Prediction.objects.filter(emergency=emergency, component=SIMILARITY).count() == 1
    assert not ActionPlan.objects.filter(emergency=emergency).exists()

    other = make_emergency()
    record_department = Department.objects.get(code="05")
    flood = EmergencyType.objects.get(name="Flood")
    UngrdRecord.objects.create(
        source_row=7,
        occurred_on="2020-03-04",
        department=record_department,
        municipality=Municipality.objects.get(code="05001"),
        emergency_type=flood,
    )
    UngrdRecord.objects.create(
        source_row=8,
        occurred_on="2021-05-06",
        department=record_department,
        emergency_type=flood,
    )
    store_prediction(
        emergency,
        active_similarity,
        [
            {"reference": "ungrd:7", "distance": 0.1, "event_type": "Flood", "occurred_on": "2020-03-04"},
            {"reference": "ungrd:8", "distance": 0.2, "event_type": "Flood", "occurred_on": "2021-05-06"},
            {"reference": f"emergency:{other.pk}", "distance": 0.3, "event_type": "Flood", "occurred_on": "2024-01-01"},
        ],
        [CODE],
    )
    html = client.get(reverse("plans:plan_detail", args=[emergency.pk])).content.decode()
    assert "Similar emergencies v1" in html
    assert "2020-03-04" in html and "MEDELLÍN" in html
    assert "2021-05-06" in html and "ANTIOQUIA" in html
    assert reverse("emergencies:emergency_detail", args=[other.pk]) in html
    assert LABEL in html
    assert reverse("plans:suggested_action_add", args=[emergency.pk]) in html


def test_add_suggested_action_creates_coded_action(client, make_emergency):
    emergency = make_emergency()
    login(client, make_user("operator", OPERATOR))
    url = reverse("plans:suggested_action_add", args=[emergency.pk])

    response = client.post(url, {"code": CODE}, follow=True)
    assert response.redirect_chain[-1][0] == reverse("plans:plan_detail", args=[emergency.pk])
    assert "The action was added." in response.content.decode()
    action = emergency.action_plan.actions.get()
    assert (action.code, action.description, action.owner) == (CODE, LABEL, None)

    assert client.post(url, {"code": CODE}).status_code == 302
    assert emergency.action_plan.actions.count() == 2


def test_add_refused_without_edit_right(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency, status=APPROVED)
    login(client, make_user("operator", OPERATOR))
    response = client.post(reverse("plans:suggested_action_add", args=[emergency.pk]), {"code": CODE})
    assert response.status_code == 403
    assert plan.actions.count() == 0

    login(client, make_user("owner", ACTION_OWNER))
    assert client.post(reverse("plans:plan_suggest", args=[emergency.pk])).status_code == 403


def test_unknown_code_is_rejected(client, make_emergency):
    emergency = make_emergency()
    login(client, make_user("operator", OPERATOR))
    url = reverse("plans:suggested_action_add", args=[emergency.pk])
    assert client.post(url, {"code": "not_a_code"}).status_code == 400
    assert client.post(url).status_code == 400
    assert not ActionPlan.objects.filter(emergency=emergency).exists()


def test_suggest_unavailable_shows_message(client, make_emergency, db):
    services.clear_cache()
    emergency = make_emergency()
    login(client, make_user("operator", OPERATOR))
    response = client.post(reverse("plans:plan_suggest", args=[emergency.pk]), follow=True)
    html = response.content.decode()
    assert "Suggestions are unavailable right now." in html
    assert Prediction.objects.count() == 0


def test_suggest_is_post_only(client, make_emergency):
    emergency = make_emergency()
    login(client, make_user("admin", ADMINISTRATOR))
    assert client.get(reverse("plans:plan_suggest", args=[emergency.pk])).status_code == 405
    assert client.get(reverse("plans:suggested_action_add", args=[emergency.pk])).status_code == 405


def test_add_button_follows_edit_right(client, make_emergency, active_similarity):
    emergency = make_emergency()
    ActionPlan.objects.create(emergency=emergency, status=APPROVED)
    store_prediction(emergency, active_similarity, [], [CODE])
    url = reverse("plans:plan_detail", args=[emergency.pk])
    add_url = reverse("plans:suggested_action_add", args=[emergency.pk])

    login(client, make_user("operator", OPERATOR))
    html = client.get(url).content.decode()
    assert LABEL in html
    assert "Add to plan" not in html
    assert add_url not in html

    login(client, make_user("admin", ADMINISTRATOR))
    html = client.get(url).content.decode()
    assert "Add to plan" in html
    assert add_url in html


def test_hidden_emergency_neighbors_are_not_disclosed(client, make_emergency, active_similarity):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    owner = make_user("owner", ACTION_OWNER)
    Action.objects.create(plan=plan, description="Own", owner=owner)
    hidden = Emergency.objects.create(
        emergency_type=EmergencyType.objects.get(name="Flood"),
        municipality=Municipality.objects.create(
            department=Department.objects.get(code="05"), code="05088", name="BELLO"
        ),
        occurred_at=timezone.now() - timedelta(days=3),
        status=REPORTED,
    )
    store_prediction(
        emergency,
        active_similarity,
        [{"reference": f"emergency:{hidden.pk}", "distance": 0.1, "event_type": "Flood", "occurred_on": "2024-01-01"}],
        [CODE],
    )
    login(client, owner)
    html = client.get(reverse("plans:plan_detail", args=[emergency.pk])).content.decode()
    assert "Similar emergencies v1" in html
    assert "BELLO" not in html
    assert reverse("emergencies:emergency_detail", args=[hidden.pk]) not in html


def test_non_ascii_digit_reference_is_ignored(client, make_emergency, active_similarity):
    emergency = make_emergency()
    store_prediction(
        emergency,
        active_similarity,
        [{"reference": "ungrd:\u00b2", "distance": 0.1, "event_type": "Flood", "occurred_on": "2024-01-01"}],
        [],
    )
    login(client, make_user("operator", OPERATOR))
    response = client.get(reverse("plans:plan_detail", args=[emergency.pk]))
    assert response.status_code == 200


def test_plan_page_uses_cards(client, make_emergency):
    emergency = make_emergency()
    plan = ActionPlan.objects.create(emergency=emergency)
    Action.objects.create(plan=plan, description="Open shelter")
    kits = Resource.objects.create(name="Food kits", kind=KIT, quantity_available=10)
    ResourceAssignment.objects.create(plan=plan, resource=kits, quantity=2)
    login(client, make_user("olga", OPERATOR))
    html = client.get(reverse("plans:plan_detail", args=[emergency.pk])).content.decode()
    compact = re.sub(r">\s+<", "><", html)
    for heading in ("Actions", "Resources", "Suggested plan"):
        assert f'<section class="card"><h2>{heading}</h2>' in compact
    assert html.count('<div class="table-wrap">') >= 2
