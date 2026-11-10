import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
PASSTHROUGH = ("SYSTEMROOT", "PATH")


def run_settings(env_vars, expression="0"):
    env = {key: os.environ[key] for key in PASSTHROUGH if key in os.environ}
    env.update({"DATABASE_URL": "", "SECRET_KEY": "", "DEBUG": ""})
    env.update(env_vars)
    code = (
        "import json, config.settings as s;"
        f"print(json.dumps({expression}))"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
    )


def test_production_without_secret_key_fails():
    result = run_settings({})
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr


def test_debug_without_secret_key_uses_dev_key():
    result = run_settings({"DEBUG": "true"})
    assert result.returncode == 0


def test_default_database_is_sqlite():
    result = run_settings(
        {"DEBUG": "true"}, "s.DATABASES['default']['ENGINE']"
    )
    assert result.returncode == 0
    assert result.stdout.strip().strip('"').endswith("sqlite3")


def test_pytest_process_uses_sqlite():
    from django.conf import settings

    assert settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")


def test_render_hostname_is_allowed():
    result = run_settings(
        {"DEBUG": "true", "RENDER_EXTERNAL_HOSTNAME": "emris.onrender.com"},
        "[s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS]",
    )
    assert result.returncode == 0
    assert "emris.onrender.com" in result.stdout
    assert "https://emris.onrender.com" in result.stdout
