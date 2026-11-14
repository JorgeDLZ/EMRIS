import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from django.template.loader import render_to_string

from apps.accounts.models import User
from apps.accounts.roles import ADMINISTRATOR, OPERATOR

TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"
STYLESHEET = Path(settings.BASE_DIR) / "static" / "css" / "main.css"


def winning_display(element: str, classes: set[str], ancestors: set[str]) -> str:
    css = re.sub(r"/\*.*?\*/", "", STYLESHEET.read_text(encoding="utf-8"), flags=re.S)
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    candidates = []
    for index, (selectors, body) in enumerate(re.findall(r"([^{}]+)\{([^{}]*)\}", css)):
        display = re.search(r"(?:^|;)\s*display\s*:\s*([^;]+)", body)
        if not display:
            continue
        for selector in selectors.split(","):
            if ":" in selector:
                continue
            compounds = re.split(r"\s*>\s*|\s+", selector.strip())
            parsed = [re.match(r"([a-z]*)((?:\.[\w-]+)*)$", compound) for compound in compounds]
            if not all(parsed):
                continue
            *outer, target = [(match.group(1), set(match.group(2).split(".")) - {""}) for match in parsed]
            if target[0] not in ("", element) or not target[1] <= classes:
                continue
            if any(tag or not names <= ancestors for tag, names in outer):
                continue
            weight = sum(len(names) for _, names in outer) + len(target[1])
            elements = 1 if target[0] else 0
            candidates.append(((weight, elements, index), display.group(1).strip()))
    return max(candidates)[1]


def test_menu_toggle_is_hidden_outside_the_phone_layout():
    toggle = winning_display("button", {"btn", "btn-secondary", "menu-toggle"}, {"app-shell", "js"})
    assert toggle == "none"


def test_no_inline_styles_in_templates():
    offenders = [
        str(path.relative_to(TEMPLATES_DIR))
        for path in TEMPLATES_DIR.rglob("*.html")
        if "style=" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_pages_include_skip_link_and_font(client, db):
    html = client.get("/accounts/login/").content.decode()
    assert 'href="#content"' in html
    assert "fonts.googleapis.com/css2?family=Inter" in html


def test_auth_pages_use_public_layout(client, db):
    for url in ("/accounts/login/", "/accounts/register/"):
        html = client.get(url).content.decode()
        assert 'class="sidebar"' not in html
        assert 'id="content"' in html


def test_login_renders_non_field_errors(client, db):
    response = client.post("/accounts/login/", {"username": "nobody", "password": "wrong"})
    html = response.content.decode()
    assert 'class="field-error"' in html


def test_not_found_page(client, db, settings):
    settings.DEBUG = False
    response = client.get("/this-page-does-not-exist/")
    assert response.status_code == 404
    html = response.content.decode()
    assert "Page not found" in html
    assert 'href="/"' in html


def test_error_pages_render(client, db):
    for name, heading in (
        ("403.html", "Access denied"),
        ("404.html", "Page not found"),
        ("500.html", "Something went wrong"),
        ("503.html", "EMRIS is temporarily unavailable."),
    ):
        html = render_to_string(name)
        assert heading in html
        assert 'href="/"' in html


def _user(username, role=None, superuser=False):
    user = User.objects.create_user(username, password="pass-12345", is_superuser=superuser)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def test_header_links_to_dashboard_for_role_user(client, db):
    client.force_login(_user("ana", role=OPERATOR))
    html = client.get(reverse("accounts:user_list"), follow=False).content.decode()
    assert "Open dashboard" in html
    assert f'href="{reverse("dashboard:index")}"' in html


def test_header_links_to_dashboard_for_superuser(client, db):
    client.force_login(_user("root", superuser=True))
    response = client.get(reverse("accounts:pending"))
    html = response.content.decode()
    assert "Open dashboard" in html
    assert f'href="{reverse("dashboard:index")}"' in html


def test_header_links_to_pending_for_user_without_role(client, db):
    client.force_login(_user("nora"))
    html = client.get(reverse("accounts:pending")).content.decode()
    assert "Check account status" in html
    assert f'href="{reverse("accounts:pending")}"' in html
    assert "Open dashboard" not in html


def test_forbidden_page_renders_for_signed_in_user(client, db):
    client.force_login(_user("ana", role=OPERATOR))
    response = client.get(reverse("accounts:user_list"))
    assert response.status_code == 403
    assert "Access denied" in response.content.decode()


def test_server_error_pages_have_no_header_actions(client, db, settings):
    settings.ROOT_URLCONF = "config.tests.test_health"
    client.force_login(_user("ana", role=OPERATOR))
    unavailable = client.get("/boom/")
    assert unavailable.status_code == 503
    for html in (unavailable.content.decode(), render_to_string("500.html")):
        assert "Log in" not in html
        assert "Open dashboard" not in html


def test_flash_messages_are_announced(client, db):
    user = User.objects.create_user("ana", password="pass-12345")
    user.groups.add(Group.objects.get(name=ADMINISTRATOR))
    client.force_login(user)
    response = client.post(
        reverse("accounts:user_role", args=[user.pk]), {"role": OPERATOR}, follow=True
    )
    html = " ".join(response.content.decode().split())
    assert '<div role="status"> <ul class="messages">' in html
