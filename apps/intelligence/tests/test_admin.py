import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import User
from apps.emergencies.tests.test_emergency_views import (  # noqa: F401
    antioquia,
    flood,
    make_emergency,
    medellin,
)
from apps.intelligence.models import IMPACT, PROFILES
from apps.intelligence.tests.test_panels import add_prediction


@pytest.mark.parametrize("model", ["modelversion", "prediction"])
def test_changelists_do_not_select_artifacts(client, db, make_emergency, model):
    emergency = make_emergency()
    add_prediction(emergency, IMPACT, {"probability": None, "reason": "not_enough_history"})
    add_prediction(emergency, PROFILES, {"profile": "Flash flood"})
    client.force_login(User.objects.create_superuser("root", password="pass-12345"))
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse(f"admin:intelligence_{model}_changelist"))
    assert response.status_code == 200
    assert not any("artifact" in query["sql"] for query in queries)
