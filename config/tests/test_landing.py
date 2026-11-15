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
STAGE_IDS = (
    "business-understanding",
    "data-engineering",
    "model-engineering",
    "model-evaluation",
    "deployment",
    "monitoring",
)
STAGE_ITEMS = {
    "business-understanding": [
        "Problem, context and stakeholders",
        "Business and machine learning objectives",
        "Questions and learning tasks",
        "Data sources, variables and target",
        "Data quality, relevance and sufficiency",
        "Feasibility, limitations and risks",
        "Success criteria",
    ],
    "data-engineering": [
        "Selected sources and features",
        "Missing values, duplicates, inconsistencies and outliers",
        "Encoding, scaling and feature engineering",
        "Data before and after processing",
        "Transformations and their justification",
        "Training, validation and test partitions",
    ],
    "model-engineering": [
        "Algorithms compared",
        "Why these algorithms",
        "Features, parameters and configuration",
        "Validation and hyperparameter tuning",
        "Experiments and domain knowledge",
    ],
    "model-evaluation": [
        "Evaluation metrics",
        "Cross-validation",
        "Model comparison",
        "Overfitting, underfitting, bias and risks",
        "Model selection",
        "Final performance on the test set",
    ],
    "deployment": [
        "Saved models and preprocessing",
        "Demonstration in the deployed application",
        "Inputs, outputs, dependencies and execution",
        "User instructions and integration",
        "Monitoring, incidents and feedback",
    ],
    "monitoring": [
        "Monitoring indicators",
        "Drift and degradation detection",
        "Review frequency, responsibilities and retraining criteria",
        "Risks, quality controls and updates",
        "Initial monitoring test (simulated data)",
    ],
}
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


def panel(html, panel_id):
    start = html.index(f'<details id="{panel_id}" class="landing-stage-panel">')
    ends = [html.find(f'<details id="{other}"', start + 1) for other in STAGE_IDS]
    return html[start : min([end for end in ends if end > 0] + [html.index('id="timeline"')])]


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


def test_landing_timeline_has_nine_milestones(client, db):
    html = landing(client)
    section = html[html.index('id="timeline"') : html.index('id="system"')]
    assert 'class="table-wrap"' in section
    body = section[section.index("<tbody>") : section.index("</tbody>")]
    rows = re.findall(r"<tr>(.*?)</tr>", body, re.S)
    assert len(rows) == 9
    assert "Foundation" in rows[0]
    assert "7–8 Nov 2026" in rows[0]
    assert "Usability and data quality" in rows[7]
    assert "14 Nov 2026" in rows[7]
    assert "CRISP-ML documentation and monitoring" in rows[8]
    assert "14–15 Nov 2026" in rows[8]


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


def test_landing_reports_the_tuning_of_c(client, db):
    html = landing(client)
    assert "0.1, 0.3, 1 and 3 gave mean PR-AUC 0.42–0.44" in html


def test_stages_are_collapsible_panels_in_order(client, db):
    html = landing(client)
    positions = [html.index(f'<details id="{panel_id}" class="landing-stage-panel">') for panel_id in STAGE_IDS]
    assert positions == sorted(positions)
    for panel_id, stage in zip(STAGE_IDS, STAGES):
        assert f'<summary><h3 class="landing-stage">{stage}</h3></summary>' in panel(html, panel_id)


def test_contents_link_every_stage(client, db):
    contents = landing(client).split('id="contents"')[1].split('id="problem"')[0]
    for panel_id in STAGE_IDS:
        assert f'href="#{panel_id}"' in contents


def test_stage_items_follow_the_course_requirements(client, db):
    html = landing(client)
    for panel_id, items in STAGE_ITEMS.items():
        section = panel(html, panel_id)
        found = re.findall(r'<details class="landing-item">\s*<summary>(.*?)</summary>', section)
        assert found == items


def test_landing_mentions_no_expert_review(client, db):
    assert "expert" not in landing(client).lower()


def test_monitoring_test_is_labelled_simulated(client, db):
    section = panel(landing(client), "monitoring")
    item = section[section.index("<summary>Initial monitoring test (simulated data)</summary>") :]
    assert "Simulated" in item
    assert "monitor_models --simulate" in item
