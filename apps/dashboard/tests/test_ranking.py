from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.roles import ACTION_OWNER, OPERATOR
from apps.dashboard.ranking import risk_ranking
from apps.dashboard.tests.test_views import make_user
from apps.intelligence.models import MUNICIPAL_RISK, ModelVersion
from apps.places.models import Department, Municipality


def make_version(ranking=None, **metrics):
    metadata = {} if ranking is None else {"ranking": ranking}
    return ModelVersion.objects.create(
        component=MUNICIPAL_RISK,
        version=1,
        artifact=b"artifact",
        primary_metric="silhouette",
        score=0.5,
        metrics={"k": 3, "insufficient_history": 0, **metrics},
        trained_on={},
        metadata=metadata,
        library_versions={},
        is_active=True,
    )


def make_places():
    antioquia = Department.objects.create(code="05", name="ANTIOQUIA")
    cundinamarca = Department.objects.create(code="25", name="CUNDINAMARCA")
    return [
        Municipality.objects.create(department=antioquia, code="05001", name="MEDELLÍN"),
        Municipality.objects.create(department=cundinamarca, code="25001", name="AGUA DE DIOS"),
        Municipality.objects.create(department=antioquia, code="05002", name="ABEJORRAL"),
    ]


def test_ranking_orders_by_level_and_resolves_names(client, db):
    make_places()
    make_version(
        [
            {"code": "05001", "level": 3, "score": 9.0},
            {"code": "25001", "level": 2, "score": 5.0},
            {"code": "05002", "level": 1, "score": 1.0},
        ],
        insufficient_history=4,
    )
    ranking = risk_ranking()
    assert [row.position for row in ranking.rows] == [1, 2, 3]
    assert [row.municipality.name for row in ranking.rows] == ["MEDELLÍN", "AGUA DE DIOS", "ABEJORRAL"]
    client.force_login(make_user("olga", OPERATOR))
    content = client.get(reverse("dashboard:ranking")).content.decode()
    assert content.index("Risk level 3 of 3") < content.index("Risk level 1 of 3")
    assert "4 municipalities with insufficient history are not ranked." in content
    assert "Municipal risk v1" in content


def test_ranking_unavailable_without_metadata(client, db):
    make_version()
    client.force_login(make_user("olga", OPERATOR))
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("dashboard:ranking"))
    assert "The ranking appears after the next retrain." in response.content.decode()
    assert not risk_ranking().available
    assert not any("artifact" in query["sql"] for query in queries)


def test_ranking_without_active_model(client, db):
    client.force_login(make_user("olga", OPERATOR))
    response = client.get(reverse("dashboard:ranking"))
    assert response.status_code == 200
    assert "No active municipal risk model." in response.content.decode()
    dashboard = client.get(reverse("dashboard:index"))
    assert "No active municipal risk model." in dashboard.content.decode()


def test_ranking_filters_by_department(client, db):
    make_places()
    make_version(
        [
            {"code": "05001", "level": 3, "score": 9.0},
            {"code": "25001", "level": 2, "score": 5.0},
            {"code": "05002", "level": 1, "score": 1.0},
            {"code": "99999", "level": 1, "score": 0.5},
        ]
    )
    client.force_login(make_user("olga", OPERATOR))
    url = reverse("dashboard:ranking")
    content = client.get(url, {"department": "05"}).content.decode()
    assert "MEDELLÍN" in content and "ABEJORRAL" in content
    assert "AGUA DE DIOS" not in content
    assert [row.position for row in risk_ranking("05").rows] == [1, 3]
    assert "99999" in client.get(url).content.decode()
    assert client.get(url, {"department": "xx"}).status_code == 200
    assert client.get(url, {"page": 999}).status_code == 200


def test_ranking_hidden_from_action_owner(client, db):
    make_version([{"code": "05001", "level": 1, "score": 1.0}])
    client.force_login(make_user("owen", ACTION_OWNER))
    assert client.get(reverse("dashboard:ranking")).status_code == 403
    dashboard = client.get(reverse("dashboard:index")).content.decode()
    assert "Municipal risk ranking" not in dashboard


def test_dashboard_shows_top_ten_for_operators(client, db):
    make_version([{"code": f"{n:05d}", "level": 1, "score": 1.0} for n in range(1, 13)])
    client.force_login(make_user("olga", OPERATOR))
    content = client.get(reverse("dashboard:index")).content.decode()
    assert "Municipal risk ranking" in content
    assert "See the full ranking" in content
    assert "00010" in content and "00011" not in content


def test_user_municipality_code_resolves(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(
        department=department, code=None, name="VEREDA NUEVA", source=Municipality.USER
    )
    make_version([{"code": f"user-{municipality.pk}", "level": 2, "score": 1.0}])
    ranking = risk_ranking()
    assert ranking.rows[0].municipality == municipality


def test_ranking_sorts_stored_entries(db):
    make_places()
    make_version(
        [
            {"code": "05002", "level": 1, "score": 1.0},
            {"code": "25001", "level": 3, "score": 2.0},
            {"code": "05001", "level": 3, "score": 8.0},
        ]
    )
    rows = risk_ranking().rows
    assert [row.code for row in rows] == ["05001", "25001", "05002"]
    assert [row.position for row in rows] == [1, 2, 3]


def test_user_code_resolves_after_municipality_gets_divipola_code(db):
    department = Department.objects.create(code="05", name="ANTIOQUIA")
    municipality = Municipality.objects.create(
        department=department, code="05999", name="VEREDA NUEVA", source=Municipality.USER
    )
    make_version([{"code": f"user-{municipality.pk}", "level": 2, "score": 1.0}])
    row = risk_ranking().rows[0]
    assert row.municipality == municipality
    assert row.municipality.department.name == "ANTIOQUIA"


def test_resolution_uses_at_most_two_municipality_queries(db):
    places = make_places()
    user_municipality = Municipality.objects.create(
        department=places[0].department, code=None, name="VEREDA NUEVA", source=Municipality.USER
    )
    make_version(
        [
            {"code": "05001", "level": 3, "score": 3.0},
            {"code": "25001", "level": 2, "score": 2.0},
            {"code": f"user-{user_municipality.pk}", "level": 1, "score": 1.0},
        ]
    )
    with CaptureQueriesContext(connection) as queries:
        rows = risk_ranking().rows
    assert all(row.municipality is not None for row in rows)
    table = Municipality._meta.db_table
    assert len([query for query in queries if f'"{table}"' in query["sql"]]) <= 2


def test_unresolved_code_row_shows_code_and_empty_department(client, db):
    make_places()
    make_version([{"code": "99999", "level": 1, "score": 1.0}])
    client.force_login(make_user("olga", OPERATOR))
    content = client.get(reverse("dashboard:ranking")).content.decode()
    row = content[content.index("<tr>", content.index("<tbody>")) : content.index("</tr>", content.index("<tbody>"))]
    cells = [" ".join(cell.split()) for cell in row.replace("<tr>", "").split("</td>")[:-1]]
    assert [cell.replace("<td>", "").strip() for cell in cells] == [
        "1", "99999", "", '<span class="badge badge-neutral">Risk level 1 of 3</span>'
    ]


def test_dashboard_shows_retrain_text_without_ranking(client, db):
    make_version()
    client.force_login(make_user("olga", OPERATOR))
    content = client.get(reverse("dashboard:index")).content.decode()
    assert "The ranking appears after the next retrain." in content
