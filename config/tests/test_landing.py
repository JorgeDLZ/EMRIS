import re
import subprocess
import sys
from pathlib import Path

from django.contrib.auth.models import Group
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.roles import OPERATOR

SECTIONS = ("problem", "objectives", "framework", "methodology", "timeline", "system", "references")
STAGES = (
    "Business and data understanding",
    "Data engineering",
    "Model engineering",
    "Model evaluation",
    "Deployment",
    "Monitoring and maintenance",
)
REFERENCE_TITLES = (
    "Towards CRISP-ML(Q): A Machine Learning Process Model with Quality Assurance Methodology",
    "CRISP-ML(Q): The ML Lifecycle Process",
    "The Machine Learning Lifecycle",
    "Ley 1523 de 2012",
    "Emergencias UNGRD V2",
    "DIVIPOLA — División Político-Administrativa de Colombia",
    "seismicity catalog, 1 June 2020 to 7 November 2026",
    "Scikit-learn: Machine Learning in Python",
)
GENERAL_OBJECTIVE = (
    "Develop and deploy a web information system that lets a risk council register, plan and track "
    "emergencies in Colombia, integrating four machine learning components trained on the UNGRD 2025 "
    "emergency history to support prioritisation and response planning."
)


def landing(client):
    return client.get(reverse("home")).content.decode()


def test_landing_is_public(client, db):
    response = client.get(reverse("home"))
    html = response.content.decode()
    assert response.status_code == 200
    assert "Emergency Management &amp; Resource Information System" in html
    assert "Log in" in html
    for section in ("top", "contents", *SECTIONS, "modules", "models"):
        assert f'id="{section}"' in html


def test_landing_follows_project_structure(client, db):
    html = landing(client)
    headings = [
        "Problem statement and justification",
        "Objectives",
        "General objective",
        "Specific objectives",
        "Reference framework",
        "CRISP-ML methodology",
        "Development timeline",
        "System and results",
        "References",
    ]
    positions = [html.index(f">{heading}</h") for heading in headings]
    assert positions == sorted(positions)
    assert len(re.findall(r"<h1[ >]", html)) == 1


def test_landing_contents_link_every_section(client, db):
    html = landing(client)
    contents = html[html.index('id="contents"') : html.index('id="problem"')]
    for section in SECTIONS:
        assert f'href="#{section}"' in contents


def test_landing_states_objectives_and_law(client, db):
    html = landing(client)
    assert GENERAL_OBJECTIVE in html
    start = html.index(">Specific objectives</h3>")
    objectives = html[start : html.index("</ol>", start)]
    assert objectives.count("<li>") == 6
    assert "Ley 1523 de 2012" in html


def test_landing_timeline_has_seven_milestones(client, db):
    html = landing(client)
    section = html[html.index('id="timeline"') : html.index('id="system"')]
    assert 'class="table-wrap"' in section
    body = section[section.index("<tbody>") : section.index("</tbody>")]
    rows = re.findall(r"<tr>(.*?)</tr>", body, re.S)
    assert len(rows) == 7
    assert "Foundation" in rows[0]
    assert "7–8 Nov 2026" in rows[0]


def test_landing_for_signed_in_user(client, db):
    user = User.objects.create_user("operator", password="pass-12345")
    user.groups.add(Group.objects.get(name=OPERATOR))
    client.force_login(user)
    html = landing(client)
    assert f'href="{reverse("dashboard:index")}"' in html
    assert "Open dashboard" in html
    assert "Register" not in html


def test_landing_for_user_without_role(client, db):
    client.force_login(User.objects.create_user("plain", password="pass-12345"))
    response = client.get(reverse("home"))
    assert response.status_code == 200
    assert f'href="{reverse("accounts:pending")}"' in response.content.decode()


def test_landing_lists_six_stages_and_references(client, db):
    html = landing(client)
    for stage in STAGES:
        assert f'<h3 class="landing-stage">{stage}</h3>' in html
    references = html[html.index('id="references"') :]
    for title in REFERENCE_TITLES:
        assert title in references


def test_landing_stages_sit_under_the_methodology_heading(client, db):
    html = landing(client)
    assert html.index(">CRISP-ML methodology</h2>") < html.index(f">{STAGES[0]}</h3>")
    for stage in STAGES:
        assert f">{stage}</h2>" not in html


def test_landing_does_not_load_ml_libraries():
    script = (
        "import os, sys, django\n"
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')\n"
        "django.setup()\n"
        "import config.views\n"
        "loaded = [name for name in ('pandas', 'sklearn') if name in sys.modules]\n"
        "sys.exit(','.join(loaded) or 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
